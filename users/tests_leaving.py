"""Leaving the company in two steps: record leaving, then deactivate."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timesheets.models import (
    Auditlog, BusinessEntry, BusinessHeader, Businesscategory, Contract, Crews,
    MainHeader, OperationsBonus, OperationsEntry, OperationsHeader,
)
from users.leaving import outstanding_items
from users.models import Accesslevel, CrewAssignment, Department, Roles, User


class LeavingBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.yesterday = cls.today - datetime.timedelta(days=1)
        levels = {lvl: Accesslevel.objects.create(accessid=lvl, accessrole=f'L{lvl}')
                  for lvl in (1, 2, 3, 5, 6, 7, 8, 9)}
        cls.dept = Department.objects.create(departmentname='Ops')
        cls.role = {lvl: Roles.objects.create(rolename=f'Role {lvl}', departmentid=cls.dept, accessid=a)
                    for lvl, a in levels.items()}
        cls.crew = Crews.objects.create(crewname='A')
        cls.contract = Contract.objects.create(contractcode='C1', contracttitle='C1')
        cls.bc = Businesscategory.objects.create(categoryname='Regular', isproductive=1, ispayable=1)

        cls.admin = cls.mk('ADM', 1)
        cls.supt = cls.mk('SUP', 2)
        cls.payroll = cls.mk('PAY', 7)
        cls.supervisor = cls.mk('SV1', 3)
        cls.employee = cls.mk('E1', 6, supervisorid=None)
        cls.miner = cls.mk('M1', 8)
        cls.miner2 = cls.mk('M2', 8)
        cls.shifter = cls.mk('S1', 5, employmenttype='Contract')

    @classmethod
    def mk(cls, eid, lvl, **extra):
        return User.objects.create(employeeid=eid, firstname=eid, lastname='Test', phonenumber='0',
                                   roleid=cls.role[lvl], isactive=True, hasaccess=True,
                                   is_temporary=False, **extra)


class RecordLeavingTests(LeavingBase):
    def test_crew_quit_records_leaving_and_keeps_account_active(self):
        seat = CrewAssignment.objects.create(employee=self.miner, startdate=self.today)
        self.client.force_login(self.supt)
        self.client.post(reverse('crew_assignments'), {
            'action': 'quit_employee', 'employee_id': 'M1', 'last_day': str(self.yesterday)})
        self.miner.refresh_from_db()
        seat.refresh_from_db()
        self.assertTrue(self.miner.isactive)
        self.assertEqual(self.miner.terminationdate, self.yesterday)
        self.assertEqual(seat.enddate, self.today)
        self.assertTrue(Auditlog.objects.filter(action='Record Leaving', recordid=self.miner.eid).exists())

    def test_future_last_day_is_refused(self):
        self.client.force_login(self.supt)
        self.client.post(reverse('crew_assignments'), {
            'action': 'quit_employee', 'employee_id': 'M1',
            'last_day': str(self.today + datetime.timedelta(days=3))})
        self.miner.refresh_from_db()
        self.assertIsNone(self.miner.terminationdate)

    def test_sysadmin_records_leaving_for_any_department_and_warns_about_reports(self):
        self.employee.supervisorid = self.supervisor
        self.employee.save()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('record_leaving', args=['SV1']), {'last_day': str(self.today)}, follow=True)
        self.supervisor.refresh_from_db()
        self.assertTrue(self.supervisor.isactive)
        self.assertEqual(self.supervisor.terminationdate, self.today)
        self.assertContains(resp, 'still supervises 1 person')
        self.assertContains(resp, 'Leaving: pending deactivation')

    def test_sysadmin_replace_records_leaving_instead_of_deactivating(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('replace_employee', args=['E1']), {
            'new_employeeid': 'E2', 'firstname': 'New', 'lastname': 'Hire', 'phonenumber': '1',
            'last_day': str(self.yesterday)})
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.isactive)
        self.assertEqual(self.employee.terminationdate, self.yesterday)
        self.assertTrue(User.objects.filter(employeeid='E2', isactive=True).exists())

    def test_crew_replace_with_leaving_checkbox(self):
        seat = CrewAssignment.objects.create(employee=self.miner, shifter=self.shifter, startdate=self.today)
        self.client.force_login(self.supt)
        self.client.post(reverse('crew_assignment_detail', args=['S1']), {
            'action': 'replace_position', 'assignment_id': seat.assignmentid,
            'existing_employeeid': 'M2', 'leaving': '1', 'leaving_last_day': str(self.yesterday)})
        self.miner.refresh_from_db()
        self.assertTrue(self.miner.isactive)
        self.assertEqual(self.miner.terminationdate, self.yesterday)
        self.assertTrue(CrewAssignment.objects.filter(employee=self.miner2, enddate__isnull=True).exists())

    def test_crew_replace_without_checkbox_is_unchanged(self):
        seat = CrewAssignment.objects.create(employee=self.miner, shifter=self.shifter, startdate=self.today)
        self.client.force_login(self.supt)
        self.client.post(reverse('crew_assignment_detail', args=['S1']), {
            'action': 'replace_position', 'assignment_id': seat.assignmentid, 'existing_employeeid': 'M2'})
        self.miner.refresh_from_db()
        self.assertIsNone(self.miner.terminationdate)


class AccessAfterLastDayTests(LeavingBase):
    def test_past_last_day_only_personal_pages(self):
        self.supervisor.terminationdate = self.yesterday
        self.supervisor.save()
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('approval_inbox'))
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)
        resp = self.client.get(reverse('my_business_drafts'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(reverse('profile')).status_code, 200)

    def test_last_day_today_still_has_full_access(self):
        self.supervisor.terminationdate = self.today
        self.supervisor.save()
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('approval_inbox'))
        self.assertEqual(resp.status_code, 200)

    def test_shifter_can_finish_own_sheets_up_to_last_day_only(self):
        self.shifter.terminationdate = self.yesterday
        self.shifter.save()
        own = OperationsHeader.objects.create(shifterid=self.shifter, shiftdate=self.yesterday,
                                              shifttype='Day', crewid=self.crew, overallstatus='Submitted')
        later = OperationsHeader.objects.create(shifterid=self.shifter, shiftdate=self.today,
                                                shifttype='Day', crewid=self.crew, overallstatus='Submitted')
        self.client.force_login(self.shifter)
        resp = self.client.get(reverse('ops_sheet', args=[own.pk]))
        self.assertNotEqual(resp.get('Location'), reverse('profile'))
        resp = self.client.get(reverse('ops_sheet', args=[later.pk]))
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)
        resp = self.client.get(reverse('my_crew'))
        self.assertRedirects(resp, reverse('profile'), fetch_redirect_response=False)


class OutstandingAndDeactivateTests(LeavingBase):
    def test_business_employee_needs_final_paid_sheet(self):
        self.employee.terminationdate = self.yesterday
        self.employee.save()
        items = outstanding_items(self.employee)
        self.assertTrue(any('Final Business timesheet' in i for i in items))
        h = BusinessHeader.objects.create(employeeid=self.employee, periodmonth=self.yesterday.month,
                                          periodyear=self.yesterday.year, overallstatus='Completed')
        BusinessEntry.objects.create(businessheaderid=h, businesscategoryid=self.bc, dateworked=self.yesterday,
                                     hoursworked=Decimal('8'), linestatus='Approved')
        self.assertEqual(outstanding_items(self.employee), ['1 Business timesheet not yet paid'])
        h.paidat = timezone.now()
        h.save()
        self.assertEqual(outstanding_items(self.employee), [])

    def test_miner_crew_lines_and_bonus(self):
        self.miner.terminationdate = self.yesterday
        self.miner.save()
        sheet = OperationsHeader.objects.create(shifterid=self.shifter, shiftdate=self.yesterday,
                                                shifttype='Day', crewid=self.crew, overallstatus='Completed')
        line = OperationsEntry.objects.create(opsheaderid=sheet, employeeid=self.miner, contractid=self.contract,
                                              hoursworked=Decimal('10'), linestatus='Approved')
        OperationsBonus.objects.create(employeeid=self.miner, bonusmonth=self.yesterday.replace(day=1),
                                       bonusratecode='2x', status='Submitted')
        self.assertEqual(len(outstanding_items(self.miner)), 2)
        line.paidat = timezone.now()
        line.save()
        OperationsBonus.objects.update(status='Applied')
        self.assertEqual(outstanding_items(self.miner), [])

    def test_deactivate_with_outstanding_is_allowed_and_logged(self):
        self.employee.terminationdate = self.yesterday
        self.employee.save()
        self.client.force_login(self.admin)
        self.client.post(reverse('deactivate_employee', args=['E1']))
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.isactive)
        log = Auditlog.objects.get(action='Deactivate Employee', recordid=self.employee.eid)
        self.assertTrue(log.newvalue['outstanding_at_deactivation'])

    def test_cannot_deactivate_someone_not_recorded_as_leaving(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('deactivate_employee', args=['E1']))
        self.assertEqual(resp.status_code, 404)


class PayrollInactiveTests(LeavingBase):
    def test_inactive_pages_and_unpaid_queue_include_inactive_people(self):
        self.employee.isactive = False
        self.employee.terminationdate = self.yesterday
        self.employee.save()
        h = BusinessHeader.objects.create(employeeid=self.employee, periodmonth=self.yesterday.month,
                                          periodyear=self.yesterday.year, overallstatus='Completed')
        BusinessEntry.objects.create(businessheaderid=h, businesscategoryid=self.bc, dateworked=self.yesterday,
                                     hoursworked=Decimal('8'), linestatus='Approved')
        self.client.force_login(self.payroll)
        resp = self.client.get(reverse('payroll_inactive'))
        self.assertContains(resp, 'Ops')
        resp = self.client.get(reverse('payroll_inactive_dept', args=[self.dept.pk]))
        self.assertContains(resp, 'E1')
        self.assertContains(resp, 'Unpaid: 1 timesheet')
        resp = self.client.get(reverse('payroll_business_unprocessed_dept', args=[self.dept.pk]))
        self.assertEqual(list(resp.context['submissions']), [h])
        h.paidat = timezone.now()
        h.save()
        resp = self.client.get(reverse('payroll_processed_business_month',
                                       args=[self.dept.pk, 'E1', self.yesterday.year, self.yesterday.month]))
        self.assertEqual(resp.status_code, 200)

    def test_search_links_applied_crew_bonus_to_member_month(self):
        OperationsBonus.objects.create(employeeid=self.miner, bonusmonth=datetime.date(2026, 10, 1),
                                       bonusratecode='2x', status='Applied')
        self.client.force_login(self.payroll)
        resp = self.client.get(reverse('timesheet_search'), {'workflow': 'crew_bonus'})
        row = resp.context['page_obj'].object_list[0]
        self.assertEqual(row['url'], reverse('payroll_ops_member_month', args=['M1', 2026, 10]))


class ChangedPagesRenderTests(LeavingBase):
    def test_crew_grid_and_replace_page_render(self):
        self.client.force_login(self.supt)
        resp = self.client.get(reverse('crew_grid'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "They're leaving the company")
        self.assertContains(resp, 'name="last_day"')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('replace_employee', args=['E1']))
        self.assertContains(resp, 'last day of work')
        resp = self.client.get(reverse('user_list'))
        self.assertContains(resp, 'Record leaving')
