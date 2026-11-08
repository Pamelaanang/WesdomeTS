import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timesheets.models import (
    Auditlog, BusinessEntry, BusinessHeader, Businesscategory, Contract, Crews,
    EmployeeBonus, MainEntry, MainHeader, OperationsBonus, OperationsEntry,
    OperationsHeader, Workcategory,
)
from users.models import Accesslevel, Department, Roles, User


class SearchTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        levels = {lvl: Accesslevel.objects.create(accessid=lvl, accessrole=f'L{lvl}') for lvl in (1, 5, 6, 7, 8, 9)}
        cls.dept = Department.objects.create(departmentname='Ops Dept')
        cls.other_dept = Department.objects.create(departmentname='Finance')
        roles = {lvl: Roles.objects.create(rolename=f'Role {lvl}', departmentid=cls.dept, accessid=a)
                 for lvl, a in levels.items()}
        finance_role = Roles.objects.create(rolename='Analyst', departmentid=cls.other_dept, accessid=levels[6])

        def mk(eid, role, first='Test', last=None, **extra):
            return User.objects.create(employeeid=eid, firstname=first, lastname=last or eid,
                                       phonenumber='0', roleid=role, isactive=True,
                                       hasaccess=True, is_temporary=False, **extra)

        cls.crew_a = Crews.objects.create(crewname='A')
        cls.crew_b = Crews.objects.create(crewname='B')
        cls.admin = mk('ADM', roles[1])
        cls.payroll = mk('PAY', roles[7])
        cls.maint = mk('M100', roles[9], first='Jane', last='Doe')
        cls.biz = mk('B200', finance_role, first='Sam', last='Lee')
        cls.shifter = mk('S300', roles[5], first='Kim', last='Park', crewid=cls.crew_a)
        cls.miner = mk('X400', roles[8], first='Ola', last='Ade', crewid=cls.crew_a)

        wc = Workcategory.objects.create(categoryname='Regular', isproductive=1, ispayable=1)
        bc = Businesscategory.objects.create(categoryname='Regular', isproductive=1, ispayable=1)
        cls.contract = Contract.objects.create(contractcode='C1', contracttitle='C1')
        now = timezone.now()

        # Maintenance: one draft, one submitted, one approved, one paid.
        def main(status, day, paid=False, hours=Decimal('8')):
            h = MainHeader.objects.create(employeeid=cls.maint, overallstatus=status, crewid=cls.crew_b,
                                          submittedat=None if status == 'Draft' else now,
                                          paidat=now if paid else None)
            MainEntry.objects.create(mainheaderid=h, shifttype='Day', hoursworked=hours,
                                     startdate=datetime.date(2026, 10, day), workcategoryid=wc,
                                     linestatus='Approved' if status == 'Completed' else 'New')
            return h
        cls.m_draft = main('Draft', 1)
        cls.m_sub = main('Submitted', 5)
        cls.m_appr = main('Completed', 10)
        cls.m_paid = main('Completed', 20, paid=True)

        cls.b_draft = BusinessHeader.objects.create(employeeid=cls.biz, periodmonth=9, periodyear=2026)
        cls.b_paid = BusinessHeader.objects.create(employeeid=cls.biz, periodmonth=10, periodyear=2026,
                                                   overallstatus='Completed', submittedat=now, paidat=now)
        BusinessEntry.objects.create(businessheaderid=cls.b_paid, businesscategoryid=bc,
                                     dateworked=datetime.date(2026, 10, 2), hoursworked=Decimal('7.5'),
                                     linestatus='Approved')

        # Daily Crew: approved sheet with two crew lines (one unpaid) and a draft.
        cls.o_appr = OperationsHeader.objects.create(shifterid=cls.shifter, shiftdate=datetime.date(2026, 10, 15),
                                                     shifttype='Night', crewid=cls.crew_a, overallstatus='Completed')
        for emp in (cls.shifter, cls.miner):
            OperationsEntry.objects.create(opsheaderid=cls.o_appr, employeeid=emp, contractid=cls.contract,
                                           hoursworked=Decimal('10'), linestatus='Approved')
        cls.o_draft = OperationsHeader.objects.create(shifterid=cls.shifter, shiftdate=datetime.date(2026, 10, 16),
                                                      shifttype='Day', crewid=cls.crew_a)

        cls.crew_bonus = OperationsBonus.objects.create(employeeid=cls.miner, bonusmonth=datetime.date(2026, 10, 1),
                                                        bonusratecode='3x', status='Submitted')
        cls.draft_bonus = OperationsBonus.objects.create(employeeid=cls.shifter, bonusmonth=datetime.date(2026, 10, 1),
                                                         bonusratecode='2x', status='Draft')
        cls.emp_bonus = EmployeeBonus.objects.create(employeeid=cls.biz, bonustype='Year-End',
                                                     periodstart=datetime.date(2026, 1, 1),
                                                     periodend=datetime.date(2026, 12, 31), bonusratecode='5',
                                                     assignedby=cls.admin, status='Applied')

    def search(self, user, **params):
        self.client.force_login(user)
        resp = self.client.get(reverse('timesheet_search'), params)
        self.assertEqual(resp.status_code, 200)
        return resp, list(resp.context['page_obj'].object_list)


class AccessTests(SearchTestBase):
    def test_other_roles_are_redirected(self):
        self.client.force_login(self.maint)
        self.assertRedirects(self.client.get(reverse('timesheet_search')), reverse('profile'),
                             fetch_redirect_response=False)

    def test_payroll_cannot_open_admin_detail(self):
        self.client.force_login(self.payroll)
        resp = self.client.get(reverse('system_timesheet_detail', args=['maintenance', self.m_paid.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Auditlog.objects.exists())


class PayrollVisibilityTests(SearchTestBase):
    def test_only_approved_and_paid(self):
        _, rows = self.search(self.payroll)
        self.assertEqual({r['bucket'] for r in rows}, {'approved', 'paid'})
        workflows = [r['workflow'] for r in rows]
        self.assertEqual(workflows.count('Maintenance'), 2)
        self.assertEqual(workflows.count('Business'), 1)
        self.assertEqual(workflows.count('Daily Crew'), 1)
        # Draft bonus hidden, submitted and applied shown.
        self.assertEqual(workflows.count('Crew Bonus'), 1)
        self.assertEqual(workflows.count('Employee Bonus'), 1)

    def test_draft_status_param_is_ignored_for_payroll(self):
        _, rows = self.search(self.payroll, status='draft')
        self.assertEqual({r['bucket'] for r in rows}, {'approved', 'paid'})

    def test_rows_link_to_existing_payroll_pages(self):
        _, rows = self.search(self.payroll, workflow='maintenance')
        urls = {r['bucket']: r['url'] for r in rows}
        self.assertEqual(urls['approved'], reverse('payroll_unprocessed_review', args=[self.dept.pk, self.m_appr.pk]))
        self.assertEqual(urls['paid'], reverse('payroll_processed_maintenance_month', args=['M100', 2026, 10]))
        _, rows = self.search(self.payroll, workflow='ops')
        self.assertEqual(rows[0]['url'], reverse('payroll_ops_sheet', args=[self.o_appr.pk]))

    def test_payroll_sees_bonus_rate(self):
        _, rows = self.search(self.payroll, workflow='crew_bonus')
        self.assertIn('3x', rows[0]['detail'])


class AdminVisibilityTests(SearchTestBase):
    def test_admin_sees_drafts_without_contents(self):
        _, rows = self.search(self.admin, workflow='maintenance', status='draft')
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]['url'])
        self.assertIsNone(rows[0]['hours'])

    def test_admin_bonus_rows_hide_rate_and_have_no_link(self):
        resp, rows = self.search(self.admin, workflow='crew_bonus')
        self.assertEqual(len(rows), 2)  # draft bonus is listed for admin
        for r in rows:
            self.assertIsNone(r['url'])
            self.assertNotIn('x', r['detail'])
        self.assertNotContains(resp, '3x')

    def test_draft_detail_refused_and_not_logged(self):
        self.client.force_login(self.admin)
        for kind, pk in [('maintenance', self.m_draft.pk), ('business', self.b_draft.pk), ('ops', self.o_draft.pk)]:
            resp = self.client.get(reverse('system_timesheet_detail', args=[kind, pk]))
            self.assertRedirects(resp, reverse('timesheet_search'), fetch_redirect_response=False)
        self.assertFalse(Auditlog.objects.exists())

    def test_detail_renders_and_logs_view(self):
        self.client.force_login(self.admin)
        for kind, pk, table in [('maintenance', self.m_sub.pk, 'MainHeader'),
                                ('business', self.b_paid.pk, 'BusinessHeader'),
                                ('ops', self.o_appr.pk, 'OperationsHeader')]:
            resp = self.client.get(reverse('system_timesheet_detail', args=[kind, pk]))
            self.assertEqual(resp.status_code, 200)
            self.assertNotContains(resp, 'name="action"')  # no action buttons
            log = Auditlog.objects.filter(tablename=table, recordid=pk, action='Viewed')
            self.assertEqual(log.count(), 1)
            self.assertEqual(log.get().employeeid, self.admin)


class FilterTests(SearchTestBase):
    def test_no_filters_returns_everything_newest_first(self):
        _, rows = self.search(self.admin)
        self.assertEqual(len(rows), 11)
        dates = [r['sort_date'] for r in rows]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_person_by_full_name_and_by_id(self):
        _, rows = self.search(self.admin, q='jane doe')
        self.assertEqual({r['workflow'] for r in rows}, {'Maintenance'})
        _, rows = self.search(self.admin, q='b200')
        self.assertEqual({r['person']['employeeid'] for r in rows}, {'B200'})

    def test_person_on_crew_sheet_matches_without_inflating_hours(self):
        _, rows = self.search(self.payroll, q='Ola', workflow='ops')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['hours'], Decimal('20'))  # both lines, not doubled or cut to one

    def test_date_range(self):
        _, rows = self.search(self.admin, workflow='maintenance', date_from='2026-10-08', date_to='2026-10-12')
        self.assertEqual([r['sort_id'] for r in rows], [self.m_appr.pk])
        _, rows = self.search(self.admin, workflow='business', date_from='2026-10-01')
        self.assertEqual([r['sort_id'] for r in rows], [self.b_paid.pk])

    def test_shift_limits_to_daily_crew(self):
        _, rows = self.search(self.admin, shift='Night')
        self.assertEqual([r['sort_id'] for r in rows], [self.o_appr.pk])

    def test_crew_and_department(self):
        _, rows = self.search(self.admin, crew=self.crew_b.pk)
        self.assertEqual({r['workflow'] for r in rows}, {'Maintenance'})
        _, rows = self.search(self.admin, dept=self.other_dept.pk)
        self.assertEqual({r['person']['employeeid'] for r in rows}, {'B200'})
