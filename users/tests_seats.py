"""A seat needs a position from its basket's discipline, or it can't show on the Crew Grid."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timesheets.models import Crews, Discipline, UnitDiscipline
from users.models import Accesslevel, CrewAssignment, Department, Position, Roles, User


class SeatPositionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        levels = {lvl: Accesslevel.objects.create(accessid=lvl, accessrole=f'L{lvl}') for lvl in (2, 5, 8)}
        dept = Department.objects.create(departmentname='Ops')
        role = {lvl: Roles.objects.create(rolename=f'Role {lvl}', departmentid=dept, accessid=a) for lvl, a in levels.items()}
        cls.crew = Crews.objects.create(crewname='A')
        cls.dev, _ = Discipline.objects.get_or_create(name='Development')
        cls.prod, _ = Discipline.objects.get_or_create(name='Production')
        UnitDiscipline.objects.create(crew=cls.crew, discipline=cls.dev)
        cls.dev_pos = Position.objects.create(positionname='Jumbo Operator', shiftertype='Development')
        cls.prod_pos = Position.objects.create(positionname='Scoop Operator', shiftertype='Production')

        def mk(eid, lvl, **extra):
            return User.objects.create(employeeid=eid, firstname=eid, lastname='T', phonenumber='0', roleid=role[lvl],
                                       isactive=True, hasaccess=True, is_temporary=False, **extra)
        cls.supt = mk('SUP', 2)
        cls.miner = mk('M1', 8)
        cls.leaving = mk('M2', 8, terminationdate=timezone.localdate())

    def add_vacant(self, employee, position=None):
        self.client.force_login(self.supt)
        data = {'action': 'bulk_add_vacant_members', 'basket': f'{self.crew.crewid}:Development',
                'employee_ids': [employee.employeeid], 'startdate': str(timezone.localdate())}
        if position:
            data[f'position_{employee.employeeid}'] = position.pk
        return self.client.post(reverse('crew_assignments'), data, follow=True)

    def test_add_without_position_is_refused(self):
        resp = self.add_vacant(self.miner)
        self.assertFalse(CrewAssignment.objects.exists())
        self.assertContains(resp, 'Choose a position')

    def test_position_from_another_discipline_is_refused(self):
        self.add_vacant(self.miner, self.prod_pos)
        self.assertFalse(CrewAssignment.objects.exists())

    def test_matching_position_is_added_and_shows_on_grid(self):
        self.add_vacant(self.miner, self.dev_pos)
        seat = CrewAssignment.objects.get(employee=self.miner)
        self.assertEqual(seat.positionid, self.dev_pos)
        resp = self.client.get(reverse('crew_grid'))
        self.assertContains(resp, 'M1')

    def test_leaving_person_cannot_be_added(self):
        resp = self.add_vacant(self.leaving, self.dev_pos)
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(CrewAssignment.objects.exists())

    def test_assign_unassigned_needs_a_matching_position(self):
        self.client.force_login(self.supt)
        base = {'action': 'assign_unassigned', 'employee_id': 'M1', 'basket': f'{self.crew.crewid}:Development'}
        self.client.post(reverse('crew_management'), {**base, 'position': self.prod_pos.pk})
        self.assertFalse(CrewAssignment.objects.exists())
        self.client.post(reverse('crew_management'), {**base, 'position': self.dev_pos.pk})
        self.assertTrue(CrewAssignment.objects.filter(employee=self.miner, positionid=self.dev_pos).exists())

    def test_eight_in_one_position_all_render(self):
        for i in range(8):
            m = User.objects.create(employeeid=f'X{i}', firstname=f'Crewman{i}', lastname='T', phonenumber='0',
                                    roleid=self.miner.roleid, isactive=True, hasaccess=True, is_temporary=False)
            self.add_vacant(m, self.dev_pos)
        self.assertEqual(CrewAssignment.objects.filter(positionid=self.dev_pos, enddate__isnull=True).count(), 8)
        resp = self.client.get(reverse('crew_grid'))
        for i in range(8):
            self.assertContains(resp, f'Crewman{i}')

    def test_position_label_shows_head_count(self):
        for i in range(5):
            m = User.objects.create(employeeid=f'J{i}', firstname=f'J{i}', lastname='T', phonenumber='0',
                                    roleid=self.miner.roleid, isactive=True, hasaccess=True, is_temporary=False)
            self.add_vacant(m, self.dev_pos)
        resp = self.client.get(reverse('crew_grid'))
        self.assertContains(resp, 'Jumbo Operator <span class="text-gray-400 font-normal" title="People currently in this position across all crews">(5)</span>', html=False)


class SpareShifterLevelTests(TestCase):
    """Lead, 1, 2 and 3 Miners can step up as a temporary Spare Shifter; Level 4 can't."""
    @classmethod
    def setUpTestData(cls):
        from timesheets.models import MinerLevel
        levels = {lvl: Accesslevel.objects.get_or_create(accessid=lvl, defaults={'accessrole': f'L{lvl}'})[0] for lvl in (2, 5, 8)}
        dept = Department.objects.create(departmentname='Ops')
        cls.miner_role = Roles.objects.create(rolename='Underground Mine Operator', departmentid=dept, accessid=levels[8])
        Roles.objects.get_or_create(rolename='Spare Shifter', defaults={'departmentid': dept, 'accessid': levels[5]})
        sup_role = Roles.objects.create(rolename='Superintendent', departmentid=dept, accessid=levels[2])
        cls.supt = User.objects.create(employeeid='SUP', firstname='S', lastname='T', phonenumber='0', roleid=sup_role,
                                       isactive=True, hasaccess=True, is_temporary=False)
        cls.crew = Crews.objects.create(crewname='A')
        dev, _ = Discipline.objects.get_or_create(name='Development')
        UnitDiscipline.objects.create(crew=cls.crew, discipline=dev)
        cls.lvl = {code: MinerLevel.objects.get_or_create(levelcode=code, defaults={'sortorder': i})[0]
                   for i, code in enumerate(['Lead', '1', '2', '3', '4'])}

    def promote(self, code):
        m = User.objects.create(employeeid=f'M{code}', firstname=code, lastname='Miner', phonenumber='0',
                                roleid=self.miner_role, minerlevel=self.lvl[code], isactive=True, hasaccess=True, is_temporary=False)
        self.client.force_login(self.supt)
        resp = self.client.post(reverse('crew_assignments'), {
            'action': 'promote_and_assign_basket_temporary', 'employee_id': m.employeeid,
            'crewid': self.crew.crewid, 'shiftertype': 'Development'})
        m.refresh_from_db()
        return resp, m

    def test_level_3_can_cover(self):
        resp, m = self.promote('3')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(m.roleid.rolename, 'Spare Shifter')

    def test_level_4_cannot(self):
        resp, m = self.promote('4')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(m.roleid.rolename, 'Underground Mine Operator')

    def test_grid_picker_gets_the_same_levels(self):
        self.client.force_login(self.supt)
        resp = self.client.get(reverse('crew_grid'))
        self.assertEqual(resp.context['spare_shifter_levels'], ['Lead', '1', '2', '3'])
        self.assertContains(resp, 'A Lead, 1, 2 or 3 Miner covers')
