import datetime
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from timesheets import leave as leave_rules
from timesheets.models import (
    Contract, Crews, LeaveAllocation, LeaveType, LieuDayLedger, MainEntry,
    MainHeader, OperationsEntry, OperationsHeader, StatHoliday,
    VacationRatePolicy, Workcategory,
)
from users.models import Accesslevel, CrewAssignment, Department, Roles, User


class LeaveTestBase(TestCase):
    """Shared fixtures for the vacation/lieu/floater leave-allocation feature.
    Built from scratch rather than relying on production seed data, since the
    test database only carries migrations, not the manually-seeded LeaveType/
    VacationRatePolicy rows that exist in the real environment."""

    @classmethod
    def setUpTestData(cls):
        cls.year = timezone.now().year

        cls.accesslevels = {
            level: Accesslevel.objects.create(accessid=level, accessrole=name)
            for level, name in [
                (3, 'Supervisor'), (4, 'Mine Captain'), (5, 'Shifter'),
                (6, 'Business Employee'), (8, 'Miner'), (9, 'Maintenance Crew'),
            ]
        }
        dept = Department.objects.create(departmentname='Test Dept')
        cls.roles = {
            level: Roles.objects.create(rolename=f'Role {level}', departmentid=dept, accessid=al)
            for level, al in cls.accesslevels.items()
        }

        cls.vacation_type = LeaveType.objects.create(leavetypename='Regular Vacation')
        cls.floater_type = LeaveType.objects.create(leavetypename='Floater')
        cls.lieu_type = LeaveType.objects.create(leavetypename='Lieu Day')
        cls.unpaid_type = LeaveType.objects.create(leavetypename='Unpaid Leave')

        VacationRatePolicy.objects.create(bucket='ops_development', effective_year=cls.year, monthly_rate_hours=12)
        VacationRatePolicy.objects.create(bucket='ops_other', effective_year=cls.year, monthly_rate_hours=10)
        VacationRatePolicy.objects.create(bucket='non_operations', effective_year=cls.year, monthly_rate_hours=12)

        cls.contract = Contract.objects.create(contractcode='TST', contracttitle='Test Contract')
        cls.workcategory = Workcategory.objects.create(categoryname='General', isproductive=1)
        cls.crew = Crews.objects.create(crewname='TST')

    def make_user(self, employeeid, level, **extra):
        return User.objects.create(
            employeeid=employeeid, firstname='Test', lastname=employeeid,
            phonenumber='0000000000', roleid=self.roles[level],
            isactive=True, hasaccess=True, is_temporary=False,
            **extra,
        )


class VacationAllocationTests(LeaveTestBase):
    def test_hire_year_proration_non_operations(self):
        emp = self.make_user('BIZ1', 6, hiredate=datetime.date(self.year, 3, 1))
        allocation = leave_rules.get_or_create_vacation_allocation(emp, self.year)
        self.assertEqual(allocation.allocatedhours, Decimal('120.00'))  # 10 months * 12
        self.assertEqual(allocation.isprorated, 1)

    def test_hire_year_proration_ops_development(self):
        emp = self.make_user('DEV1', 5, hiredate=datetime.date(self.year, 3, 1), shiftertype='Development')
        allocation = leave_rules.get_or_create_vacation_allocation(emp, self.year)
        self.assertEqual(allocation.allocatedhours, Decimal('120.00'))  # 10 months * 12

    def test_hire_year_proration_ops_other(self):
        emp = self.make_user('PROD1', 5, hiredate=datetime.date(self.year, 3, 1), shiftertype='Production')
        allocation = leave_rules.get_or_create_vacation_allocation(emp, self.year)
        self.assertEqual(allocation.allocatedhours, Decimal('100.00'))  # 10 months * 10

    def test_no_hiredate_never_blocks(self):
        emp = self.make_user('NOHIRE1', 9, hiredate=None)
        self.assertIsNone(leave_rules.get_or_create_vacation_allocation(emp, self.year))
        self.assertIsNone(leave_rules.validate_vacation_entry(emp, self.year, Decimal('9999')))

    def test_annual_refresh_creates_independent_full_allocation(self):
        emp = self.make_user('BIZ2', 6, hiredate=datetime.date(self.year - 2, 6, 1))
        this_year_alloc = leave_rules.get_or_create_vacation_allocation(emp, self.year)
        self.assertEqual(this_year_alloc.allocatedhours, Decimal('144.00'))  # full 12 months
        self.assertEqual(this_year_alloc.isprorated, 0)

        VacationRatePolicy.objects.create(bucket='non_operations', effective_year=self.year + 1, monthly_rate_hours=15)
        next_year_alloc = leave_rules.get_or_create_vacation_allocation(emp, self.year + 1)
        self.assertEqual(next_year_alloc.allocatedhours, Decimal('180.00'))  # 12 * 15, independent row
        self.assertNotEqual(this_year_alloc.allocationid, next_year_alloc.allocationid)

    def test_rate_policy_effective_dating_is_data_only(self):
        VacationRatePolicy.objects.create(bucket='ops_other', effective_year=self.year + 1, monthly_rate_hours=12)
        self.assertEqual(leave_rules.get_monthly_vacation_rate('ops_other', self.year), Decimal('10'))
        self.assertEqual(leave_rules.get_monthly_vacation_rate('ops_other', self.year + 1), Decimal('12'))


class LieuEligibilityTests(LeaveTestBase):
    def test_business_filers_are_lieu_eligible(self):
        for level in (3, 4, 5, 6):
            emp = self.make_user(f'ELIG{level}', level)
            self.assertTrue(leave_rules.is_lieu_eligible(emp), f'access_level {level} should be lieu-eligible')

    def test_hourly_workers_are_not_lieu_eligible(self):
        for level in (8, 9):
            emp = self.make_user(f'HOURLY{level}', level)
            self.assertFalse(leave_rules.is_lieu_eligible(emp), f'access_level {level} should not be lieu-eligible')

    def test_lieu_day_banked_when_no_hours_logged(self):
        emp = self.make_user('LIEU1', 6)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        StatHoliday.objects.create(statname='Test Stat', statdate=stat_date, province='ON')
        self.assertEqual(leave_rules.get_lieu_balance(emp), 1)
        self.assertTrue(LieuDayLedger.objects.filter(employeeid=emp, status='Banked').exists())

    def test_lieu_day_not_banked_when_hours_logged(self):
        from timesheets.models import BusinessEntry, BusinessHeader
        emp = self.make_user('LIEU2', 6)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        StatHoliday.objects.create(statname='Test Stat', statdate=stat_date, province='ON')
        header = BusinessHeader.objects.create(employeeid=emp, periodmonth=stat_date.month, periodyear=stat_date.year)
        BusinessEntry.objects.create(
            businessheaderid=header, dateworked=stat_date, hoursworked=Decimal('8'), linestatus='Approved',
        )
        self.assertEqual(leave_rules.get_lieu_balance(emp), 0)

    def test_hourly_worker_never_banks_lieu_even_with_zero_hours(self):
        emp = self.make_user('HOURLY_LIEU', 9)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        StatHoliday.objects.create(statname='Test Stat', statdate=stat_date, province='ON')
        self.assertEqual(leave_rules.get_lieu_balance(emp), 0)
        self.assertFalse(LieuDayLedger.objects.filter(employeeid=emp).exists())

    def test_same_date_shared_across_provinces_banks_only_once(self):
        emp = self.make_user('SHAREDDATE1', 6)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        StatHoliday.objects.create(statname='Shared ON', statdate=stat_date, province='ON')
        StatHoliday.objects.create(statname='Shared QC', statdate=stat_date, province='QC')
        self.assertEqual(leave_rules.get_lieu_balance(emp), 1)
        self.assertEqual(LieuDayLedger.objects.filter(employeeid=emp).count(), 1)

    def test_muted_holiday_prunes_unused_banked_ledger_row(self):
        emp = self.make_user('MUTEPRUNE1', 6)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        sh = StatHoliday.objects.create(statname='Will Be Muted', statdate=stat_date, province='QC')
        self.assertEqual(leave_rules.get_lieu_balance(emp), 1)

        sh.isactive = 0
        sh.save()
        self.assertEqual(leave_rules.get_lieu_balance(emp), 0)
        self.assertFalse(LieuDayLedger.objects.filter(employeeid=emp).exists())

    def test_muting_does_not_revoke_an_already_used_lieu_day(self):
        emp = self.make_user('MUTEPRUNE2', 6)
        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        sh = StatHoliday.objects.create(statname='Will Be Muted After Use', statdate=stat_date, province='QC')
        self.assertEqual(leave_rules.get_lieu_balance(emp), 1)

        ledger = LieuDayLedger.objects.get(employeeid=emp, statholidayid=sh)
        ledger.status = 'Used'
        ledger.save()

        sh.isactive = 0
        sh.save()
        leave_rules.sync_lieu_ledger_for_employee(emp)
        ledger.refresh_from_db()
        self.assertEqual(ledger.status, 'Used')


class ApprovalDeductionTests(LeaveTestBase):
    """Verifies balances only reflect approved entries, never draft/pending/rejected."""

    def test_maintenance_deduction_only_on_approval(self):
        emp = self.make_user('MAINT1', 9, hiredate=datetime.date(self.year, 1, 1))
        supervisor = self.make_user('SUP1', 3)
        emp.supervisorid = supervisor
        emp.save()

        header = MainHeader.objects.create(employeeid=emp)
        entry = MainEntry.objects.create(
            mainheaderid=header, leavetypeid=self.vacation_type,
            hoursworked=Decimal('40'), startdate=datetime.date(self.year, 6, 1),
            linestatus='New',
        )
        self.assertEqual(leave_rules.get_vacation_approved_hours(emp, self.year), 0)

        c = Client()
        c.force_login(supervisor)
        resp = c.post(f'/supervisor/review/{header.mainheaderid}/', {'action': 'approve', 'entryid': entry.mainentryid})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(leave_rules.get_vacation_approved_hours(emp, self.year), Decimal('40'))

    def test_rejected_entry_never_affects_balance(self):
        emp = self.make_user('MAINT2', 9, hiredate=datetime.date(self.year, 1, 1))
        supervisor = self.make_user('SUP2', 3)
        emp.supervisorid = supervisor
        emp.save()

        header = MainHeader.objects.create(employeeid=emp)
        entry = MainEntry.objects.create(
            mainheaderid=header, leavetypeid=self.vacation_type,
            hoursworked=Decimal('40'), startdate=datetime.date(self.year, 6, 1),
            linestatus='New',
        )
        c = Client()
        c.force_login(supervisor)
        c.post(f'/supervisor/review/{header.mainheaderid}/', {'action': 'reject', 'entryid': entry.mainentryid})
        self.assertEqual(leave_rules.get_vacation_approved_hours(emp, self.year), 0)


class OverageValidationTests(LeaveTestBase):
    def test_vacation_overage_blocked_for_business_employee(self):
        emp = self.make_user('OVER1', 6, hiredate=datetime.date(self.year, 1, 1))
        c = Client()
        c.force_login(emp)
        header_resp = self._make_business_header(emp)

        resp = c.post(f'/business/{header_resp.businessheaderid}/', {
            'action': 'save_entry', 'category_selection': f'lt_{self.vacation_type.leavetypeid}',
            'dateworked': f'{self.year}-06-01', 'shifttype': 'Day', 'hoursworked': '9999',
        })
        self.assertEqual(resp.status_code, 302)

        from timesheets.models import BusinessEntry
        self.assertEqual(BusinessEntry.objects.filter(businessheaderid=header_resp).count(), 0)

    def test_unpaid_leave_not_capped(self):
        emp = self.make_user('OVER2', 6, hiredate=datetime.date(self.year, 1, 1))
        c = Client()
        c.force_login(emp)
        header = self._make_business_header(emp)

        resp = c.post(f'/business/{header.businessheaderid}/', {
            'action': 'save_entry', 'category_selection': f'lt_{self.unpaid_type.leavetypeid}',
            'dateworked': f'{self.year}-06-01', 'shifttype': 'Day', 'hoursworked': '999',
        })
        self.assertEqual(resp.status_code, 302)
        from timesheets.models import BusinessEntry
        self.assertEqual(BusinessEntry.objects.filter(businessheaderid=header).count(), 1)

    def test_overage_message_differs_by_lieu_eligibility(self):
        biz_emp = self.make_user('MSG1', 6, hiredate=datetime.date(self.year, 1, 1))
        maint_emp = self.make_user('MSG2', 9, hiredate=datetime.date(self.year, 1, 1))

        biz_error = leave_rules.validate_vacation_entry(biz_emp, self.year, Decimal('9999'))
        maint_error = leave_rules.validate_vacation_entry(maint_emp, self.year, Decimal('9999'))

        self.assertIn('Lieu Day', biz_error)
        self.assertNotIn('Lieu Day', maint_error)
        self.assertIn('Unpaid Leave', maint_error)

    def _make_business_header(self, emp):
        from timesheets.models import BusinessHeader
        today = timezone.now().date()
        return BusinessHeader.objects.create(employeeid=emp, periodmonth=today.month, periodyear=today.year, overallstatus='Draft')


class LieuConsumptionTests(LeaveTestBase):
    def test_lieu_day_consumed_on_business_approval(self):
        from timesheets.models import BusinessEntry, BusinessHeader
        emp = self.make_user('CONSUME1', 6, hiredate=datetime.date(self.year, 1, 1))
        supervisor = self.make_user('SUP3', 3)
        emp.supervisorid = supervisor
        emp.save()

        stat_date = timezone.now().date() - datetime.timedelta(days=1)
        StatHoliday.objects.create(statname='Test Stat', statdate=stat_date, province='ON')
        ledger = LieuDayLedger.objects.create(employeeid=emp, statholidayid=StatHoliday.objects.first())
        self.assertEqual(leave_rules.get_lieu_balance(emp), 1)

        header = BusinessHeader.objects.create(employeeid=emp, periodmonth=stat_date.month, periodyear=stat_date.year)
        entry = BusinessEntry.objects.create(
            businessheaderid=header, leavetypeid=self.lieu_type, dateworked=stat_date,
            hoursworked=Decimal('8'), linestatus='New',
        )

        c = Client()
        c.force_login(supervisor)
        resp = c.post(f'/business/review/{header.businessheaderid}/', {'action': 'approve', 'entryid': entry.businessentryid})
        self.assertEqual(resp.status_code, 302)

        ledger.refresh_from_db()
        self.assertEqual(ledger.status, 'Used')
        self.assertEqual(ledger.used_entry_id, entry.businessentryid)
        self.assertEqual(leave_rules.get_lieu_balance(emp), 0)


class OperationsLeaveParityTests(LeaveTestBase):
    def test_crew_member_type_derived_from_shifter(self):
        shifter = self.make_user('SHIFT1', 5, shiftertype='Development', crewid=self.crew)
        member = self.make_user('CREW1', 8)
        CrewAssignment.objects.create(shifter=shifter, employee=member, startdate=timezone.now().date())

        self.assertEqual(leave_rules.get_operations_employee_type(member), 'Development')
        self.assertEqual(leave_rules.get_vacation_bucket(member), 'ops_development')

    def test_lieu_day_never_offered_on_ops_sheet(self):
        shifter = self.make_user('SHIFT2', 5, shiftertype='Production', crewid=self.crew)
        member = self.make_user('CREW2', 8, hiredate=datetime.date(self.year, 1, 1))
        CrewAssignment.objects.create(shifter=shifter, employee=member, startdate=timezone.now().date())

        c = Client()
        c.force_login(shifter)
        header = OperationsHeader.objects.create(
            shifterid=shifter, shiftdate=timezone.now().date(), shifttype='Day',
            crewid=self.crew, overallstatus='Draft',
        )
        resp = c.get(f'/operations/{header.opsheaderid}/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'>Lieu Day<', resp.content)

    def test_operations_vacation_overage_blocked(self):
        shifter = self.make_user('SHIFT3', 5, shiftertype='Production', crewid=self.crew)
        member = self.make_user('CREW3', 8, hiredate=datetime.date(self.year, 1, 1))
        CrewAssignment.objects.create(shifter=shifter, employee=member, startdate=timezone.now().date())

        c = Client()
        c.force_login(shifter)
        header = OperationsHeader.objects.create(
            shifterid=shifter, shiftdate=timezone.now().date(), shifttype='Day',
            crewid=self.crew, overallstatus='Draft',
        )
        resp = c.post(f'/operations/{header.opsheaderid}/', {
            'action': 'add_row', 'employeeid': member.eid, 'contractid': self.contract.contractid,
            'category_selection': f'lt_{self.vacation_type.leavetypeid}', 'hoursworked': '9999',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(OperationsEntry.objects.filter(opsheaderid=header).count(), 0)
