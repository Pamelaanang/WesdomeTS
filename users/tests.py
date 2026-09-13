import datetime

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from timesheets.models import (
    Account, BusinessEntry, BusinessHeader, Businesscategory, OperationsEntry,
    OperationsHeader, Opscategory,
)
from timesheets.tests import LeaveTestBase


class MineCaptainDashboardTests(LeaveTestBase):
    """The Mine Captain's profile dashboard previously only showed their own
    personal timesheet stats and their crew's Ops daily sheets — nothing for
    the Shifters' personal Business timesheets awaiting the captain's claim-
    based review, even though a Quick Action link to that inbox already
    existed. This mirrors business_approval_inbox's al=4 ownership query."""

    def test_shifters_pending_stat_reflects_claim_model(self):
        captain = self.make_user('DASHCAP1', 4)
        other_captain = self.make_user('DASHCAP2', 4)
        shifter = self.make_user('DASHSHIFT1', 5, shiftertype='Production', crewid=self.crew)
        bcat = Businesscategory.objects.create(categoryname='Dash Regular', isproductive=1)
        header = BusinessHeader.objects.create(
            employeeid=shifter, periodyear=self.year, periodmonth=1, overallstatus='Submitted',
        )
        entry = BusinessEntry.objects.create(
            businessheaderid=header, businesscategoryid=bcat,
            dateworked=datetime.date(self.year, 1, 5), hoursworked=8, linestatus='New',
        )

        c = Client()
        c.force_login(captain)
        resp = c.get(reverse('profile'))
        self.assertContains(resp, "Shifters' Submissions")
        self.assertEqual(resp.context['shifters_pending'], 1)

        # Claiming the header (by approving one entry) keeps it visible to
        # the claiming captain...
        c.post(reverse('review_business_timesheet', args=[header.businessheaderid]), {
            'action': 'approve', 'entryid': entry.businessentryid,
        })
        header.refresh_from_db()
        self.assertEqual(header.bh_approvedby_capt_id, captain.eid)

        resp2 = c.get(reverse('profile'))
        self.assertEqual(resp2.context['shifters_pending'], 1)

        # ...but hides it from every other captain, since it's no longer unclaimed.
        c.force_login(other_captain)
        resp3 = c.get(reverse('profile'))
        self.assertEqual(resp3.context['shifters_pending'], 0)

    def test_ops_pending_stat_counts_unclaimed_sheet_even_without_supervisorid(self):
        """Regression: a Shifter with no supervisorid set at all (real prod
        data can look like this) submits a crew sheet — any captain should
        see it via the claim model, exactly like ops_approval_inbox does.
        The dashboard stat previously used shifterid__in=<direct reports>,
        which silently missed shifters with no supervisorid on file."""
        captain = self.make_user('DASHCAP3', 4)
        shifter = self.make_user('DASHSHIFT2', 5, shiftertype='Production', crewid=self.crew)
        self.assertIsNone(shifter.supervisorid_id)

        member = self.make_user('DASHCREW1', 8)
        account = Account.objects.create(accountcode='DASHACC1', accounttitle='Dash Account')
        opscat = Opscategory.objects.create(categoryname='Dash Ops Regular', isproductive=1)
        header = OperationsHeader.objects.create(
            shifterid=shifter, shiftdate=timezone.now().date(), shifttype='Day',
            crewid=self.crew, overallstatus='Submitted',
        )
        OperationsEntry.objects.create(
            opsheaderid=header, employeeid=member, contractid=self.contract,
            accountid=account, opscategoryid=opscat, hoursworked=8, linestatus='New',
        )

        c = Client()
        c.force_login(captain)
        resp = c.get(reverse('profile'))
        self.assertEqual(resp.context['ops_pending_captain'], 1)
