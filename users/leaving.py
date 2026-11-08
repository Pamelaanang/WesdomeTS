"""Leaving the company, in two steps.

1. Record leaving: User.terminationdate is set to the person's last day of
   work. Their seat is freed straight away, but the account stays active so
   they can still log in, submit their final timesheet, and be paid.
2. Deactivate: the System Admin does this from User Management once nothing
   up to the last day is left to pay. Deactivating with something still
   outstanding is allowed after a warning, and the Audit Log records what was
   outstanding.

"Leaving" means isactive=True with a terminationdate set. Once the last day
has passed, LeavingAccessMiddleware limits the person to their own profile and
personal timesheets. A Shifter can also finish their own crew sheets dated up
to their last day, so their crew's hours still reach Payroll.
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone


def is_leaving(user):
    return bool(user.isactive and user.terminationdate)


def past_last_day(user, today=None):
    today = today or timezone.localdate()
    return is_leaving(user) and user.terminationdate < today


def personal_workflow(user):
    """Which personal timesheet this person files: 'maintenance', 'business' or None.
    Matches the sidebar: Maintenance Crew (9) files Maintenance sheets;
    Supervisor (3), Mine Captain (4), Business Employee (6) and staff (non-contract)
    Shifters (5) file Business sheets; everyone else files none of their own."""
    al = user.access_level
    if al == 9:
        return 'maintenance'
    if al in (3, 4, 6) or (al == 5 and user.employmenttype != 'Contract'):
        return 'business'
    return None


def outstanding_items(user):
    """What's still left to pay for this person up to their last day, as short
    readable lines. An empty list means they're ready to deactivate."""
    from timesheets.models import (
        BusinessHeader, EmployeeBonus, MainEntry, MainHeader, OperationsBonus,
        OperationsEntry, OperationsHeader,
    )
    last_day = user.terminationdate
    items = []

    flow = personal_workflow(user)
    if flow == 'maintenance':
        has_final = MainEntry.objects.filter(
            mainheaderid__employeeid=user,
            startdate__year=last_day.year, startdate__month=last_day.month,
            startdate__lte=last_day,
        ).exclude(mainheaderid__overallstatus='Draft').exists()
        if not has_final:
            items.append(f'Final Maintenance timesheet for {last_day:%B %Y} not submitted')
        unpaid = MainHeader.objects.filter(employeeid=user, paidat__isnull=True, mainentry__isnull=False).distinct().count()
        if unpaid:
            items.append(f'{unpaid} Maintenance timesheet{"s" if unpaid != 1 else ""} not yet paid')
    elif flow == 'business':
        final = BusinessHeader.objects.filter(
            employeeid=user, periodyear=last_day.year, periodmonth=last_day.month,
        ).exclude(overallstatus='Draft')
        if not final.exists():
            items.append(f'Final Business timesheet for {last_day:%B %Y} not submitted')
        unpaid = BusinessHeader.objects.filter(employeeid=user, paidat__isnull=True, businessentry__isnull=False).distinct().count()
        if unpaid:
            items.append(f'{unpaid} Business timesheet{"s" if unpaid != 1 else ""} not yet paid')

    # Their own lines on crew sheets. Rejected lines are never paid, so they
    # don't count as outstanding.
    crew_lines = OperationsEntry.objects.filter(
        employeeid=user, opsheaderid__shiftdate__lte=last_day, paidat__isnull=True,
    ).exclude(linestatus='Rejected').count()
    if crew_lines:
        items.append(f'{crew_lines} crew-sheet line{"s" if crew_lines != 1 else ""} not yet paid')

    # A Shifter's own crew sheets that haven't been approved yet.
    open_sheets = OperationsHeader.objects.filter(
        shifterid=user, shiftdate__lte=last_day,
    ).exclude(overallstatus='Completed')
    drafts = open_sheets.filter(overallstatus__in=['Draft', 'Revision Required']).count()
    in_review = open_sheets.count() - drafts
    if drafts:
        items.append(f'{drafts} crew sheet{"s" if drafts != 1 else ""} they lead not yet submitted')
    if in_review:
        items.append(f'{in_review} crew sheet{"s" if in_review != 1 else ""} they lead awaiting approval')

    bonuses = (OperationsBonus.objects.filter(employeeid=user, status='Submitted').count()
               + EmployeeBonus.objects.filter(employeeid=user, status='Submitted').count())
    if bonuses:
        items.append(f'{bonuses} bonus{"es" if bonuses != 1 else ""} waiting at Payroll')
    return items


def record_leaving_plain(actor, target, last_day):
    """Record leaving for someone with no crew seat. Crew seats go through
    users.views._retire_shifter, which also hands the basket on."""
    from timesheets.audit import log_action
    from .models import CrewAssignment
    old = target.terminationdate
    target.terminationdate = last_day
    target.save(update_fields=['terminationdate'])
    CrewAssignment.objects.filter(employee=target, enddate__isnull=True).update(
        enddate=timezone.localdate(), active_employee_key=None)
    log_action(actor, 'Record Leaving', 'Employee', target.eid,
               {'terminationdate': str(old) if old else None}, {'terminationdate': str(last_day)})


def deactivate(actor, target):
    """Step 2. Returns the items that were still outstanding (also logged)."""
    from timesheets.audit import log_action
    outstanding = outstanding_items(target) if target.terminationdate else []
    target.isactive = False
    target.save(update_fields=['isactive'])
    log_action(actor, 'Deactivate Employee', 'Employee', target.eid,
               {'isactive': True},
               {'isactive': False, 'last_day': str(target.terminationdate) if target.terminationdate else None,
                'outstanding_at_deactivation': outstanding})
    return outstanding


# Pages a person can still use after their last day: their own profile and
# personal timesheets, pay history and bonuses.
LEAVING_ALLOWED = {
    'login', 'logout', 'forgot_password', 'password_reset', 'profile', 'upload_profile_photo', 'home',
    # Maintenance personal timesheets
    'new_timesheet', 'add_entry', 'delete_draft', 'my_drafts', 'view_timesheet',
    'my_timesheets_approved', 'my_timesheets_approved_month', 'my_timesheets_paid', 'my_timesheets_paid_month',
    # Business personal timesheets
    'new_business_timesheet', 'add_business_entry', 'delete_business_draft', 'my_business_drafts',
    'my_business_approved', 'my_business_approved_month', 'my_bonuses',
    # Contract crew members' own pay
    'my_pay_history', 'my_pay_history_month',
}
# A Shifter may still finish their own crew sheets dated up to the last day.
LEAVING_SHIFTER_SHEETS = {'my_ops_sheets', 'ops_sheet', 'delete_ops_draft', 'accounts_for_contract'}


class LeavingAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated or not past_last_day(user):
            return None
        match = getattr(request, 'resolver_match', None)
        name = match.url_name if match else None
        if name is None or name in LEAVING_ALLOWED:
            return None  # static/media/admin, or an allowed page
        if name in LEAVING_SHIFTER_SHEETS and user.access_level == 5:
            pk = view_kwargs.get('pk')
            if pk is None:
                return None
            from timesheets.models import OperationsHeader
            if OperationsHeader.objects.filter(opsheaderid=pk, shifterid=user,
                                               shiftdate__lte=user.terminationdate).exists():
                return None
        messages.error(request, f'Your last day was {fmt_day(user.terminationdate)}. '
                                'You can only use your profile and your own timesheets now.')
        return redirect('profile')


def fmt_day(d):
    """'Nov 8, 2026' without the Linux-only %-d format code."""
    return f'{d:%b} {d.day}, {d.year}'
