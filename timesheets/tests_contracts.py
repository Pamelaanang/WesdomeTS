"""Contract-Cost Center/Account page: System Admin access, creating/editing/retiring
series, contracts and cost centers/accounts, and no duplicate codes."""
from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from timesheets.models import Account, Auditlog, Contract, ContractSeries, MinerLevel, contracts_by_miner_level
from users.models import Accesslevel, Department, Roles, User


class ContractPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        dept = Department.objects.create(departmentname='Ops')

        def mk(eid, lvl):
            al = Accesslevel.objects.get_or_create(accessid=lvl, defaults={'accessrole': f'L{lvl}'})[0]
            role = Roles.objects.create(rolename=f'R{lvl}', departmentid=dept, accessid=al)
            return User.objects.create(employeeid=eid, firstname=eid, lastname='T', phonenumber='0', roleid=role,
                                       isactive=True, hasaccess=True, is_temporary=False)
        cls.admin_user = mk('ADM', 1)
        cls.supt = mk('SUP', 2)
        cls.employee = mk('E1', 6)
        cls.level1 = MinerLevel.objects.get_or_create(levelcode='1', defaults={'sortorder': 2})[0]

    def post(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse('contract_account_management'), data, follow=True)

    def test_access(self):
        for user, ok in [(self.admin_user, True), (self.supt, True), (self.employee, False)]:
            self.client.force_login(user)
            resp = self.client.get(reverse('contract_account_management'))
            self.assertEqual(resp.status_code == 200, ok, user.employeeid)

    def test_create_series_contract_and_cost_centre(self):
        self.post(self.admin_user, action='create_series', seriesname='Development')
        series = ContractSeries.objects.get(seriesname='Development')
        self.post(self.admin_user, action='create_contract', contractcode=' C-104 ', contracttitle='Jumbo drilling',
                  level_ids=[self.level1.pk], series_ids=[series.pk])
        contract = Contract.objects.get(contractcode='C-104')  # spaces trimmed
        self.assertEqual(list(contract.levels.all()), [self.level1])
        self.assertEqual(list(contract.series.all()), [series])
        self.post(self.admin_user, action='create_account', accountcode='CC-9', accounttitle='Underground dev')
        self.assertTrue(Account.objects.filter(accountcode='CC-9').exists())
        self.assertEqual(Auditlog.objects.filter(action='Created').count(), 3)
        # The new contract is offered to Miners at its level.
        self.assertIn(contract.contractid, [c['id'] for c in contracts_by_miner_level()[str(self.level1.pk)]])

    def test_duplicates_are_refused_ignoring_case(self):
        Contract.objects.create(contractcode='C-1', contracttitle='First')
        resp = self.post(self.supt, action='create_contract', contractcode='c-1', contracttitle='Second')
        self.assertEqual(Contract.objects.count(), 1)
        self.assertContains(resp, 'already used by First')
        Account.objects.create(accountcode='A1', accounttitle='One')
        self.post(self.supt, action='create_account', accountcode='a1', accounttitle='Two')
        self.assertEqual(Account.objects.count(), 1)
        ContractSeries.objects.create(seriesname='Production')
        self.post(self.supt, action='create_series', seriesname='production ')
        self.assertEqual(ContractSeries.objects.count(), 1)

    def test_edit_and_deactivate_contract(self):
        c = Contract.objects.create(contractcode='C-2', contracttitle='Old')
        c.levels.add(self.level1)
        self.client.force_login(self.admin_user)
        url = reverse('contract_detail', args=[c.pk])
        self.client.post(url, {'action': 'edit_contract', 'contractid': c.pk, 'contractcode': 'C-2', 'contracttitle': 'New'})
        c.refresh_from_db()
        self.assertEqual(c.contracttitle, 'New')
        self.client.post(url, {'action': 'set_contract_active', 'rowid': c.pk, 'active': '0'})
        c.refresh_from_db()
        self.assertEqual(c.isactive, 0)
        self.assertContains(self.client.get(reverse('contract_series', args=['inactive'])), 'C-2')
        self.assertEqual(contracts_by_miner_level()[str(self.level1.pk)], [])
        self.client.post(url, {'action': 'set_contract_active', 'rowid': c.pk, 'active': '1'})
        c.refresh_from_db()
        self.assertEqual(c.isactive, 1)

    def test_contract_page_links_levels_series_and_accounts(self):
        c = Contract.objects.create(contractcode='C-5', contracttitle='Bolting')
        s = ContractSeries.objects.create(seriesname='Development')
        a = Account.objects.create(accountcode='CC-1', accounttitle='Dev')
        self.client.force_login(self.supt)
        url = reverse('contract_detail', args=[c.pk])
        self.client.post(url, {'action': 'add_level', 'contractid': c.pk, 'levelid': self.level1.pk})
        self.client.post(url, {'action': 'add_series', 'contractid': c.pk, 'target_series_id': s.pk})
        self.client.post(url, {'action': 'link_account', 'contractid': c.pk, 'accountid': a.pk})
        self.assertEqual(list(c.levels.all()), [self.level1])
        self.assertEqual(list(c.series.all()), [s])
        self.assertTrue(c.contractaccount_set.filter(accountid=a).exists())
        self.client.post(url, {'action': 'unlink_account', 'contractid': c.pk, 'accountid': a.pk})
        self.assertFalse(c.contractaccount_set.exists())
        # Creating a contract sets everything from the form and returns to the same page, modal closed.
        resp = self.client.post(reverse('contract_series', args=[s.pk]),
                                {'action': 'create_contract', 'contractcode': 'C-6', 'contracttitle': 'Six',
                                 'contractdescription': 'Desc', 'level_ids': [self.level1.pk], 'series_ids': [s.pk],
                                 'account_ids': [a.pk], 'next': reverse('contract_series', args=[s.pk]) + '?show=no_level'})
        self.assertRedirects(resp, reverse('contract_series', args=[s.pk]) + '?show=no_level', fetch_redirect_response=False)
        new = Contract.objects.get(contractcode='C-6')
        self.assertEqual((new.contractdescription, list(new.levels.all()), list(new.series.all())), ('Desc', [self.level1], [s]))
        self.assertTrue(new.contractaccount_set.filter(accountid=a).exists())

    def test_back_link_stays_inside_the_app(self):
        c = Contract.objects.create(contractcode='C-7', contracttitle='Seven')
        self.client.force_login(self.supt)
        resp = self.client.get(reverse('contract_detail', args=[c.pk]), {'back': 'javascript:alert(1)'})
        self.assertEqual(resp.context['back_url'], reverse('contract_account_management'))
        resp = self.client.get(reverse('contract_detail', args=[c.pk]), {'back': '//evil.example/x'})
        self.assertEqual(resp.context['back_url'], reverse('contract_account_management'))

    def test_series_delete_only_when_empty(self):
        s = ContractSeries.objects.create(seriesname='Logistics')
        c = Contract.objects.create(contractcode='C-3', contracttitle='Haul')
        c.series.add(s)
        self.post(self.supt, action='delete_series', seriesid=s.pk)
        self.assertTrue(ContractSeries.objects.filter(pk=s.pk).exists())
        c.series.remove(s)
        self.post(self.supt, action='delete_series', seriesid=s.pk)
        self.assertFalse(ContractSeries.objects.filter(pk=s.pk).exists())

    def test_admin_site_cannot_delete_contracts_or_cost_centers(self):
        request = RequestFactory().get('/')
        request.user = self.admin_user
        self.assertFalse(admin.site._registry[Contract].has_delete_permission(request))
        self.assertFalse(admin.site._registry[Account].has_delete_permission(request))

    def test_overview_cards_flag_what_needs_attention(self):
        s = ContractSeries.objects.create(seriesname='Production')
        ready = Contract.objects.create(contractcode='P-1', contracttitle='Ready')
        ready.series.add(s); ready.levels.add(self.level1)
        ready.contractaccount_set.create(accountid=Account.objects.create(accountcode='A9', accounttitle='Nine'))
        bare = Contract.objects.create(contractcode='P-2', contracttitle='Bare')
        bare.series.add(s)
        Contract.objects.create(contractcode='L-1', contracttitle='Loose')
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('contract_account_management'))
        card = resp.context['cards'][0]
        self.assertEqual((card['count'], card['needs_account'], card['no_level']), (2, 1, 1))
        self.assertEqual(resp.context['loose']['count'], 1)
        # Series page lists rows and filters to just the ones needing attention.
        resp = self.client.get(reverse('contract_series', args=[s.pk]), {'show': 'needs_account'})
        self.assertEqual([c.contractcode for c in resp.context['contracts']], ['P-2'])
        # Search finds a contract from the overview.
        resp = self.client.get(reverse('contract_account_management'), {'q': 'loose'})
        self.assertEqual([c.contractcode for c in resp.context['results']], ['L-1'])

    def test_every_page_renders(self):
        c = Contract.objects.create(contractcode='C-9', contracttitle='Loose')
        s = ContractSeries.objects.create(seriesname='Dev')
        self.client.force_login(self.admin_user)
        for url in [reverse('contract_account_management'), reverse('contract_series', args=[s.pk]),
                    reverse('contract_series', args=['unassigned']), reverse('contract_series', args=['inactive']),
                    reverse('contract_detail', args=[c.pk]), reverse('contract_accounts')]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_modal_panel_and_reopen_after_a_change(self):
        s = ContractSeries.objects.create(seriesname='Dev')
        c = Contract.objects.create(contractcode='C-8', contracttitle='Eight')
        c.series.add(s)
        self.client.force_login(self.supt)
        series_url = reverse('contract_series', args=[s.pk])
        # The modal loads just the panel, and its forms come back to the series page with it reopened.
        resp = self.client.get(reverse('contract_detail', args=[c.pk]), {'partial': '1', 'back': series_url})
        self.assertTemplateUsed(resp, 'timesheets/_contract_panel.html')
        self.assertNotContains(resp, '<html')
        self.assertEqual(resp.context['return_url'], f'{series_url}?open={c.pk}')
        # A change posted from the modal (it submits to the series page) lands back there, modal open.
        resp = self.client.post(series_url + f'?open={c.pk}', {'action': 'add_level', 'contractid': c.pk,
                                                             'levelid': self.level1.pk, 'next': resp.context['return_url']})
        self.assertRedirects(resp, f'{series_url}?open={c.pk}', fetch_redirect_response=False)
        self.assertEqual(list(c.levels.all()), [self.level1])
        # Rows open the modal rather than navigating away.
        self.assertContains(self.client.get(series_url), f'onclick="openContract({c.pk})"')

    def test_bulk_link_several_accounts_to_series(self):
        s = ContractSeries.objects.create(seriesname='Bulk')
        c1 = Contract.objects.create(contractcode='B-1', contracttitle='One')
        c2 = Contract.objects.create(contractcode='B-2', contracttitle='Two')
        retired = Contract.objects.create(contractcode='B-3', contracttitle='Old', isactive=0)
        for c in (c1, c2, retired):
            c.series.add(s)
        a1 = Account.objects.create(accountcode='CC-A', accounttitle='A')
        a2 = Account.objects.create(accountcode='CC-B', accounttitle='B')
        c1.contractaccount_set.create(accountid=a1)  # already linked: left alone
        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('contract_series', args=[s.pk]),
                                {'action': 'bulk_assign_account', 'seriesid': s.pk, 'accountid': [a1.pk, a2.pk]},
                                follow=True)
        for c in (c1, c2):
            self.assertEqual(set(c.contractaccount_set.values_list('accountid', flat=True)), {a1.pk, a2.pk})
        self.assertFalse(retired.contractaccount_set.exists())
        self.assertContains(resp, 'CC-A, CC-B linked to all 2 active contracts in Bulk (3 new links).')
        self.assertEqual(Auditlog.objects.filter(action='Linked').count(), 3)
        resp = self.client.post(reverse('contract_series', args=[s.pk]),
                                {'action': 'bulk_assign_account', 'seriesid': s.pk}, follow=True)
        self.assertContains(resp, 'Pick at least one cost center/account to link.')
