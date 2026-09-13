import datetime
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from timesheets import leave as leave_rules
from timesheets.models import (
    Account, BusinessEntry, BusinessHeader, Businesscategory, Contract,
    Crews, LeaveAllocation, LeaveType, LieuDayLedger, MainEntry,
    MainHeader, OperationsEntry, OperationsHeader, Opscategory, StatHoliday,
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


class BulkApproveTests(LeaveTestBase):
    """Bulk-approve lets a reviewer check several still-pending entries and
    approve them in one request, alongside (not instead of) the existing
    per-entry Approve/Reject flow. Rejection stays individual since it
    requires a note."""

    def test_business_bulk_approve_only_touches_selected_new_entries(self):
        supervisor = self.make_user('BSUP1', 3)
        employee = self.make_user('BEMP1', 6, supervisorid=supervisor)
        bcat = Businesscategory.objects.create(categoryname='Regular', isproductive=1)
        header = BusinessHeader.objects.create(
            employeeid=employee, periodyear=self.year, periodmonth=1, overallstatus='Submitted',
        )
        pending1 = BusinessEntry.objects.create(
            businessheaderid=header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 1, 5), hoursworked=8, linestatus='New',
        )
        pending2 = BusinessEntry.objects.create(
            businessheaderid=header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 1, 6), hoursworked=8, linestatus='New',
        )
        already_approved = BusinessEntry.objects.create(
            businessheaderid=header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 1, 7), hoursworked=8, linestatus='Approved',
        )

        c = Client()
        c.force_login(supervisor)
        resp = c.post(reverse('review_business_timesheet', args=[header.businessheaderid]), {
            'action': 'bulk_approve',
            'entryids': [pending1.businessentryid, pending2.businessentryid],
        })
        self.assertEqual(resp.status_code, 302)

        pending1.refresh_from_db()
        pending2.refresh_from_db()
        already_approved.refresh_from_db()
        header.refresh_from_db()
        self.assertEqual(pending1.linestatus, 'Approved')
        self.assertEqual(pending2.linestatus, 'Approved')
        self.assertEqual(pending1.approvedby_id, supervisor.eid)
        self.assertIsNotNone(pending1.approvedat)
        self.assertEqual(header.overallstatus, 'In Progress')
        # Untouched: was already Approved before the bulk action, not re-processed.
        self.assertEqual(already_approved.approvedby_id, None)

    def test_business_bulk_approve_ignores_entries_from_another_header(self):
        supervisor = self.make_user('BSUP2', 3)
        employee = self.make_user('BEMP2', 6, supervisorid=supervisor)
        other_employee = self.make_user('BEMP2B', 6, supervisorid=supervisor)
        bcat = Businesscategory.objects.create(categoryname='Regular2', isproductive=1)
        header = BusinessHeader.objects.create(employeeid=employee, periodyear=self.year, periodmonth=2, overallstatus='Submitted')
        other_header = BusinessHeader.objects.create(employeeid=other_employee, periodyear=self.year, periodmonth=2, overallstatus='Submitted')
        mine = BusinessEntry.objects.create(
            businessheaderid=header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 2, 1), hoursworked=8, linestatus='New',
        )
        foreign = BusinessEntry.objects.create(
            businessheaderid=other_header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 2, 1), hoursworked=8, linestatus='New',
        )

        c = Client()
        c.force_login(supervisor)
        c.post(reverse('review_business_timesheet', args=[header.businessheaderid]), {
            'action': 'bulk_approve',
            'entryids': [mine.businessentryid, foreign.businessentryid],
        })

        mine.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(mine.linestatus, 'Approved')
        self.assertEqual(foreign.linestatus, 'New')  # belongs to a different header — never touched

    def test_maintenance_bulk_approve(self):
        supervisor = self.make_user('MSUP1', 3)
        employee = self.make_user('MEMP1', 9, supervisorid=supervisor)
        header = MainHeader.objects.create(employeeid=employee, overallstatus='Submitted')
        entry1 = MainEntry.objects.create(
            mainheaderid=header, workcategoryid=self.workcategory,
            startdate=datetime.date(self.year, 1, 5), hoursworked=8, linestatus='New',
        )
        entry2 = MainEntry.objects.create(
            mainheaderid=header, workcategoryid=self.workcategory,
            startdate=datetime.date(self.year, 1, 6), hoursworked=8, linestatus='New',
        )

        c = Client()
        c.force_login(supervisor)
        resp = c.post(reverse('review_timesheet', args=[header.mainheaderid]), {
            'action': 'bulk_approve',
            'entryids': [entry1.mainentryid, entry2.mainentryid],
        })
        self.assertEqual(resp.status_code, 302)

        entry1.refresh_from_db()
        entry2.refresh_from_db()
        header.refresh_from_db()
        self.assertEqual(entry1.linestatus, 'Approved')
        self.assertEqual(entry2.linestatus, 'Approved')
        self.assertEqual(header.overallstatus, 'In Progress')

    def test_operations_bulk_approve_claims_header(self):
        captain = self.make_user('OCAP1', 4)
        shifter = self.make_user('OSHIFT1', 5, shiftertype='Production', crewid=self.crew)
        member1 = self.make_user('OCREW1', 8)
        member2 = self.make_user('OCREW2', 8)
        account = Account.objects.create(accountcode='ACC1', accounttitle='Test Account')
        opscat = Opscategory.objects.create(categoryname='Ops Regular', isproductive=1)
        header = OperationsHeader.objects.create(
            shifterid=shifter, shiftdate=timezone.now().date(), shifttype='Day',
            crewid=self.crew, overallstatus='Submitted',
        )
        entry1 = OperationsEntry.objects.create(
            opsheaderid=header, employeeid=member1, contractid=self.contract,
            accountid=account, opscategoryid=opscat, hoursworked=8, linestatus='New',
        )
        entry2 = OperationsEntry.objects.create(
            opsheaderid=header, employeeid=member2, contractid=self.contract,
            accountid=account, opscategoryid=opscat, hoursworked=8, linestatus='New',
        )

        c = Client()
        c.force_login(captain)
        resp = c.post(reverse('review_ops_sheet', args=[header.opsheaderid]), {
            'action': 'bulk_approve',
            'entryids': [entry1.opsentryid, entry2.opsentryid],
        })
        self.assertEqual(resp.status_code, 302)

        entry1.refresh_from_db()
        entry2.refresh_from_db()
        header.refresh_from_db()
        self.assertEqual(entry1.linestatus, 'Approved')
        self.assertEqual(entry2.linestatus, 'Approved')
        self.assertEqual(header.ohapprovedby_capt_id, captain.eid)
        self.assertEqual(header.overallstatus, 'In Progress')

    def test_bulk_approve_ui_renders_on_all_three_review_pages(self):
        supervisor = self.make_user('UISUP1', 3)
        employee = self.make_user('UIEMP1', 6, supervisorid=supervisor)
        bcat = Businesscategory.objects.create(categoryname='UI Regular', isproductive=1)
        bheader = BusinessHeader.objects.create(employeeid=employee, periodyear=self.year, periodmonth=3, overallstatus='Submitted')
        BusinessEntry.objects.create(
            businessheaderid=bheader, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 3, 1), hoursworked=8, linestatus='New',
        )
        c = Client()
        c.force_login(supervisor)
        resp = c.get(reverse('review_business_timesheet', args=[bheader.businessheaderid]))
        html = resp.content.decode()
        self.assertIn('row-checkbox', html)
        self.assertIn('id="select-all"', html)
        self.assertIn('Bulk Approve Selected', html)

        maint_supervisor = self.make_user('UISUP2', 3)
        maint_employee = self.make_user('UIEMP2', 9, supervisorid=maint_supervisor)
        mheader = MainHeader.objects.create(employeeid=maint_employee, overallstatus='Submitted')
        MainEntry.objects.create(
            mainheaderid=mheader, workcategoryid=self.workcategory,
            startdate=datetime.date(self.year, 1, 10), hoursworked=8, linestatus='New',
        )
        c.force_login(maint_supervisor)
        resp2 = c.get(reverse('review_timesheet', args=[mheader.mainheaderid]))
        html2 = resp2.content.decode()
        self.assertIn('row-checkbox', html2)
        self.assertIn('id="select-all"', html2)
        self.assertIn('Bulk Approve Selected', html2)

        captain = self.make_user('UICAP1', 4)
        shifter = self.make_user('UISHIFT1', 5, shiftertype='Production', crewid=self.crew)
        member = self.make_user('UICREW1', 8)
        account = Account.objects.create(accountcode='UIACC1', accounttitle='UI Test Account')
        opscat = Opscategory.objects.create(categoryname='UI Ops Regular', isproductive=1)
        oheader = OperationsHeader.objects.create(
            shifterid=shifter, shiftdate=timezone.now().date(), shifttype='Day',
            crewid=self.crew, overallstatus='Submitted',
        )
        OperationsEntry.objects.create(
            opsheaderid=oheader, employeeid=member, contractid=self.contract,
            accountid=account, opscategoryid=opscat, hoursworked=8, linestatus='New',
        )
        c.force_login(captain)
        resp3 = c.get(reverse('review_ops_sheet', args=[oheader.opsheaderid]))
        html3 = resp3.content.decode()
        self.assertIn('row-checkbox', html3)
        self.assertIn('toggleSelectAll(this)', html3)
        self.assertIn('Bulk Approve Selected', html3)


class SupervisorApprovedMonthWorkOrderColumnTests(LeaveTestBase):
    """supervisor_approved_month.html serves both Maintenance (MainEntry, has
    a real Work Order/SAP ID field) and Business (BusinessEntry, no such
    concept at all) employees through one shared template. The Work Order
    column must only render for Maintenance — it was previously always shown,
    permanently blank ('—') for every Business employee."""

    def test_work_order_column_shown_for_maintenance_hidden_for_business(self):
        supervisor = self.make_user('WOSUP1', 3)
        maint_employee = self.make_user('WOMAINT1', 9, supervisorid=supervisor)
        biz_employee = self.make_user('WOBIZ1', 6, supervisorid=supervisor)

        mheader = MainHeader.objects.create(employeeid=maint_employee, overallstatus='Completed')
        MainEntry.objects.create(
            mainheaderid=mheader, workcategoryid=self.workcategory, sapworkid='WO-1000042',
            startdate=datetime.date(self.year, 1, 5), hoursworked=8, linestatus='Approved',
        )
        bcat = Businesscategory.objects.create(categoryname='WO Regular', isproductive=1)
        bheader = BusinessHeader.objects.create(employeeid=biz_employee, periodyear=self.year, periodmonth=1, overallstatus='Completed')
        BusinessEntry.objects.create(
            businessheaderid=bheader, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 1, 5), hoursworked=8, linestatus='Approved',
        )

        c = Client()
        c.force_login(supervisor)

        resp_maint = c.get(reverse('supervisor_approved_month', args=[maint_employee.employeeid, self.year, 1]))
        html_maint = resp_maint.content.decode()
        self.assertIn('Work Order', html_maint)
        self.assertIn('WO-1000042', html_maint)

        resp_biz = c.get(reverse('supervisor_approved_month', args=[biz_employee.employeeid, self.year, 1]))
        html_biz = resp_biz.content.decode()
        self.assertNotIn('Work Order', html_biz)
