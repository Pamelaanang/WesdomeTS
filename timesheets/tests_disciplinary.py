import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timesheets.models import (
    Contract, Crews, LeaveType, OperationsEntry, OperationsHeader, Opscategory, Workcategory,
)
from timesheets.views import (
    _category_error, _disciplinary_hours, _payable_hours_split, _worked_hours_breakdown,
)
from users.models import Accesslevel, Department, Roles, User


class DisciplinaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Both rows come from the 0046 seeding migration.
        cls.action = Opscategory.objects.get(categoryname='Disciplinary Action')
        cls.suspension = LeaveType.objects.get(leavetypename='Disciplinary Suspension')
        cls.regular = Opscategory.objects.create(categoryname='Regular', isproductive=1, ispayable=True)

        levels = {lvl: Accesslevel.objects.get_or_create(accessid=lvl, defaults={'accessrole': f'L{lvl}'})[0]
                  for lvl in (2, 5, 7, 8)}
        dept = Department.objects.create(departmentname='Ops Dept')
        roles = {lvl: Roles.objects.create(rolename=f'Role {lvl}', departmentid=dept, accessid=a)
                 for lvl, a in levels.items()}

        def mk(eid, lvl, **extra):
            return User.objects.create(employeeid=eid, firstname='T', lastname=eid, phonenumber='0',
                                       roleid=roles[lvl], isactive=True, hasaccess=True,
                                       is_temporary=False, **extra)
        crew = Crews.objects.create(crewname='A')
        cls.supt = mk('SUP1', 2)
        cls.payroll = mk('PAY1', 7)
        cls.shifter = mk('SH1', 5, crewid=crew)
        cls.miner = mk('MN1', 8, crewid=crew)
        contract = Contract.objects.create(contractcode='C1', contracttitle='C1')

        header = OperationsHeader.objects.create(shifterid=cls.shifter, shiftdate=datetime.date(2026, 10, 15),
                                                 shifttype='Day', crewid=crew, overallstatus='Completed')
        now = timezone.now()

        def line(hours, **cat):
            return OperationsEntry.objects.create(opsheaderid=header, employeeid=cls.miner, contractid=contract,
                                                  hoursworked=Decimal(hours), linestatus='Approved',
                                                  paidat=now, **cat)
        # Half day worked, half on suspension; plus a full paid disciplinary shift.
        line('6', opscategoryid=cls.regular)
        line('6', leavetypeid=cls.suspension)
        line('12', opscategoryid=cls.action)
        cls.draft_header = OperationsHeader.objects.create(shifterid=cls.shifter, shiftdate=timezone.now().date(),
                                                           shifttype='Night', crewid=crew)

    def test_seeded_flags(self):
        self.assertTrue(self.action.ispayable)
        self.assertTrue(self.action.isdisciplinary)
        self.assertFalse(self.suspension.ispayable)
        self.assertTrue(self.suspension.isdisciplinary)

    def test_pay_buckets(self):
        entries = OperationsEntry.objects.filter(employeeid=self.miner)
        payable, non_payable, total = _payable_hours_split(entries, 'opscategoryid')
        self.assertEqual((payable, non_payable, total), (Decimal('18'), Decimal('6'), Decimal('24')))
        regular, stat, ot = _worked_hours_breakdown(entries, 'opscategoryid', 'opsheaderid__shiftdate', set())
        self.assertEqual(regular, Decimal('18'))  # suspension is never worked time
        self.assertEqual(_disciplinary_hours(entries), (Decimal('12'), Decimal('6')))

    def test_suspension_only_valid_on_ops_sheet(self):
        sel = f'lt_{self.suspension.pk}'
        self.assertIsNone(_category_error(sel))
        self.assertIsNotNone(_category_error(sel, Workcategory, 'wc_'))

    def test_ops_sheet_dropdown_has_disciplinary_group(self):
        self.client.force_login(self.shifter)
        html = self.client.get(reverse('ops_sheet', args=[self.draft_header.pk])).content.decode()
        self.assertIn('<optgroup label="Disciplinary">', html)
        self.assertIn('Disciplinary Action (paid, no bonus)', html)
        self.assertIn('Disciplinary Suspension (no pay)', html)
        work, rest = html.split('<optgroup label="Work Categories">', 1)[1].split('</optgroup>', 1)
        self.assertNotIn('Disciplinary', work)
        leave = rest.split('<optgroup label="Leave">', 1)[1].split('</optgroup>', 1)[0]
        self.assertNotIn('Disciplinary', leave)

    def test_bonus_panels_note_hours(self):
        for user, name in ((self.supt, 'superintendent_ops_member_month'), (self.payroll, 'payroll_ops_member_month')):
            self.client.force_login(user)
            today = timezone.now()
            year, month = (2026, 10) if name.startswith('superintendent') else (today.year, today.month)
            html = self.client.get(reverse(name, args=[self.miner.employeeid, year, month])).content.decode()
            self.assertIn('12', html.split('Disciplinary hours this month', 1)[1][:400], name)
            self.assertIn('paid, but no bonus on these hours', html, name)
            self.assertIn('Disciplinary Suspension: no pay', html, name)
            self.assertIn('>Disciplinary</span>', html, name)
