"""User Management: department cards, department pages with tabs, search, leaving list."""
import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import Accesslevel, Department, Roles, User


class UserManagementPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        al1 = Accesslevel.objects.create(accessid=1, accessrole='System Admin')
        al6 = Accesslevel.objects.create(accessid=6, accessrole='Employee')
        cls.ops = Department.objects.create(departmentname='Operations')
        cls.fin = Department.objects.create(departmentname='Finance')
        admin_role = Roles.objects.create(rolename='System Administrator', departmentid=cls.ops, accessid=al1)
        ops_role = Roles.objects.create(rolename='Clerk', departmentid=cls.ops, accessid=al6)
        fin_role = Roles.objects.create(rolename='Analyst', departmentid=cls.fin, accessid=al6)

        def mk(eid, role, **extra):
            defaults = dict(firstname=eid, lastname='Smith', phonenumber='0', roleid=role,
                            isactive=True, hasaccess=True, is_temporary=False)
            defaults.update(extra)
            return User.objects.create(employeeid=eid, **defaults)
        cls.admin = mk('ADM', admin_role)
        mk('O1', ops_role)
        mk('O2', ops_role, is_temporary=True)
        mk('O3', ops_role, terminationdate=timezone.localdate() - datetime.timedelta(days=1))
        mk('O4', ops_role, isactive=False)
        mk('F1', fin_role, firstname='Jane', lastname='Doe')

    def setUp(self):
        self.client.force_login(self.admin)

    def test_overview_cards_count_by_status(self):
        resp = self.client.get(reverse('user_list'))
        ops = next(d for d in resp.context['departments'] if d.pk == self.ops.pk)
        # ADM, O1, O2 active; O3 leaving; O4 inactive.
        self.assertEqual((ops.active_count, ops.leaving_count, ops.inactive_count), (3, 1, 1))
        self.assertEqual(resp.context['leaving_count'], 1)
        self.assertContains(resp, 'Leaving: pending deactivation')

    def test_department_tabs(self):
        url = reverse('user_department', args=[self.ops.pk])
        expect = {'active': {'ADM', 'O1', 'O2'}, 'leaving': {'O3'}, 'inactive': {'O4'},
                  'temporary': {'O2'}, 'all': {'ADM', 'O1', 'O2', 'O3', 'O4'}}
        for tab, ids in expect.items():
            resp = self.client.get(url, {'tab': tab})
            self.assertEqual({u.employeeid for u in resp.context['people']}, ids, tab)

    def test_search_across_departments(self):
        resp = self.client.get(reverse('user_list'), {'q': 'jane doe'})
        self.assertEqual([u.employeeid for u in resp.context['results']], ['F1'])

    def test_leaving_page(self):
        resp = self.client.get(reverse('user_leaving'))
        self.assertEqual([r['user'].employeeid for r in resp.context['leaving_list']], ['O3'])

    def test_actions_return_to_the_page_they_came_from(self):
        dept_url = reverse('user_department', args=[self.ops.pk]) + '?tab=active'
        resp = self.client.post(reverse('record_leaving', args=['O1']),
                                {'last_day': str(timezone.localdate()), 'next': dept_url})
        self.assertRedirects(resp, dept_url, fetch_redirect_response=False)
        resp = self.client.post(reverse('record_leaving', args=['O2']),
                                {'last_day': str(timezone.localdate()), 'next': 'https://evil.example/'})
        self.assertRedirects(resp, reverse('user_list'), fetch_redirect_response=False)

    def test_other_roles_cannot_open_the_pages(self):
        self.client.force_login(User.objects.get(employeeid='O1'))
        for url in [reverse('user_list'), reverse('user_department', args=[self.ops.pk]), reverse('user_leaving')]:
            self.assertRedirects(self.client.get(url), reverse('profile'), fetch_redirect_response=False)
