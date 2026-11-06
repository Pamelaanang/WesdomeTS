from django.shortcuts import render, redirect, get_object_or_404
from django.http import Http404
from django.contrib.auth import login, logout
from django.conf import settings
from users.forms import UserLoginForm
from users.models import User, CrewAssignment, Roles, Position, CrewCoverage, Department, BasketLead
from django.contrib.auth.decorators import login_required
import random
import string
import os
from PIL import Image, UnidentifiedImageError
from collections import Counter
from django.utils import timezone
from django.db import transaction
from datetime import date as date_type
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from timesheets.models import MainHeader, MainEntry, OperationsHeader, OperationsEntry, BusinessHeader, BusinessEntry, Crews, Contract, Account, MinerLevel, contracts_by_miner_level, CrewGroup, Discipline, UnitDiscipline, Auditlog, OperationsBonus, EmployeeBonus
from timesheets.crew_units import also_covers_error, single_crews
from timesheets.models import BasketShifter, UnitDiscipline, basket_for
from django.db.models import Count, Q, Sum
from django.urls import reverse, resolve, Resolver404
from django.utils.http import url_has_allowed_host_and_scheme
from calendar import month_name as _month_name
from timesheets import leave as leave_rules
from timesheets.audit import log_action


def _leave_balance_context(user, year):
    if not user.roleid.showsleavebalance:
        return {'show_leave_balances': False}
    return {
        'show_leave_balances': True,
        'vacation_remaining': leave_rules.get_vacation_remaining(user, year),
        'floater_available': leave_rules.get_floater_available(user, year),
        'lieu_balance': leave_rules.get_lieu_balance(user) if leave_rules.is_lieu_eligible(user) else None,
    }


def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.hasaccess:
                form.add_error(None, "This account does not have application access.")
                return render(request, 'login.html', {'form': form})
            login(request, user)
            if user.is_temporary:
                return redirect('password_reset')
            return redirect('profile')
    else:
        form = UserLoginForm(request)
    
    return render(request, 'login.html', {'form': form})

def logout_view(request):
    logout(request)
    return render(request, 'logout.html')


def forgot_password_view(request):
    """Self-service reset: Employee ID + the phone number on file proves it's
    them, same as the System Admin's own reset button does today — no new
    delivery channel, just a self-serve trigger for the existing one."""
    if request.method == 'POST':
        employeeid = request.POST.get('employeeid', '').strip()
        phonenumber = request.POST.get('phonenumber', '').strip()
        user = User.objects.filter(
            employeeid=employeeid, phonenumber=phonenumber, isactive=True, hasaccess=True,
        ).first()
        if user:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            user.set_password(temp_password)
            user.is_temporary = True
            user.lastresetdate = timezone.now()
            user.save()
            log_action(user, 'Forgot Password', 'Employee', user.eid, new_values={'is_temporary': True})
            # TODO: replace with real SMS via Twilio
            print(f"SMS to {user.phonenumber}: The temporary password for {user.firstname} {user.lastname} is {temp_password}")
        # Same message either way — doesn't confirm or deny whether that Employee ID exists.
        messages.success(request, "If that Employee ID and phone number match our records, a temporary password has been sent by SMS.")
        return redirect('login')
    return render(request, 'forgot_password.html')


def csrf_failure(request, reason=""):
    """Replaces Django's bare CSRF error page. Most often hit when a form was
    left open in one tab while a session refresh (or a fresh login) happened
    in another — the open tab's token no longer matches. There's nothing to
    recover (the browser's already left the form by the time this renders),
    so this just explains it in plain terms and sends them back to retry,
    rather than a raw technical error page."""
    return render(request, 'csrf_failure.html', status=403)


def _miner_level_choices():
    return [(level.levelid, level.levelcode) for level in MinerLevel.objects.all()]


def _level_from_post(raw):
    raw = (raw or '').strip()
    return MinerLevel.objects.filter(pk=int(raw)).first() if raw.isdigit() else None


def _staff_level():
    return MinerLevel.objects.get(levelcode='Staff')


def _level_code(level):
    return level.levelcode if level else None


@login_required(login_url='login')
def user_list_view(request):
    if request.user.access_level != 1:
        return redirect('profile')
    users = User.objects.select_related('roleid__departmentid').order_by('roleid__departmentid__departmentname', 'lastname')
    roles = Roles.objects.select_related('departmentid').order_by('departmentid__departmentname', 'rolename')
    active_supervisors = User.objects.filter(isactive=True).select_related('roleid').order_by('lastname', 'firstname')
    crews = Crews.objects.filter(isactive=1)
    contracts_for_modal = contracts_by_miner_level()
    accounts = Account.objects.filter(isactive=1)

    # Show every active department, not just ones that already have a member —
    # otherwise a brand-new department's first employee could never be added.
    users_by_dept = {}
    for u in users:
        dept_id = u.roleid.departmentid_id if u.roleid else None
        users_by_dept.setdefault(dept_id, []).append(u)
    department_list = [
        {'department': d, 'users': users_by_dept.get(d.departmentid, [])}
        for d in Department.objects.filter(isactive=1).order_by('departmentname')
    ]

    return render(request, 'user_list.html', {
        'users': users,
        'department_list': department_list,
        'roles': roles,
        'active_supervisors': active_supervisors,
        'crews': crews,
        'contracts_for_modal': contracts_for_modal,
        'accounts': accounts,
        'employment_type_choices': User.EMPLOYMENT_TYPE_CHOICES,
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
        'minerlevel_choices': _miner_level_choices(),
    })


@login_required(login_url='login')
def generate_password(request, employeeid):
    if request.user.access_level != 1:
        return redirect('profile')
    
    user = User.objects.get(employeeid=employeeid)
    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.set_password(temp_password)
    user.is_temporary = True
    user.lastresetdate = timezone.now()
    user.save()

    # TODO: replace with real SNS via Twilio

    print(f"SMS to {user.phonenumber}: The temporary password for {user.firstname} {user.lastname} is {temp_password}")   
    return redirect('user_list')

@login_required(login_url='login')
def reactivate_employee(request, employeeid):
    if request.user.access_level != 1:
        return redirect('profile')

    user = get_object_or_404(User, employeeid=employeeid, isactive=False)
    if user.onboarding_status == 'pending':
        messages.error(request, f'{user.firstname} {user.lastname} is awaiting IT onboarding. IT activates them from IT Onboarding.')
        return redirect('user_list')

    # Quitting (_retire_shifter) clears crewid/shiftertype and ends the basket seat,
    # and reactivating can't guess which crew/discipline they should come back to —
    # so a Shifter or Miner comes back with no seat, same as a brand-new hire, and
    # gets placed the same way: from Crew Management's Unassigned list.
    needs_placement = user.access_level in (5, 8)

    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.set_password(temp_password)
    user.isactive = True
    user.hasaccess = True
    user.is_temporary = True
    user.terminationdate = None
    user.save()
    log_action(request.user, 'Reactivate Employee', 'Employee', user.eid, {'isactive': False}, {'isactive': True})
    print(f"SMS to {user.phonenumber}: Temp password for {user.firstname} {user.lastname} is {temp_password}")
    if needs_placement:
        messages.success(
            request,
            f'{user.firstname} {user.lastname} reactivated. Temporary password sent. '
            f'They have no crew yet — place them from Crew Management → Unassigned.'
        )
    else:
        messages.success(request, f'{user.firstname} {user.lastname} reactivated. Temporary password sent.')
    return redirect('user_list')


@login_required(login_url='login')
def password_reset_view(request):
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        if new_password == confirm_password:
            request.user.set_password(new_password)
            request.user.is_temporary = False
            request.user.save()
            update_session_auth_hash(request, request.user)  # Keep the user logged in after password change
            return redirect('profile')
        else:
            error_message = "Passwords do not match."
            return render(request, 'password_reset.html', {'error_message': error_message})
    return render(request, 'password_reset.html')


@login_required(login_url='login')
def profile(request):
    user = request.user
    al = user.access_level
    today = timezone.now().date()

    if al == 1:  # System Admin
        total_active = User.objects.filter(isactive=True).count()
        total_inactive = User.objects.filter(isactive=False).count()
        dept_breakdown = User.objects.filter(isactive=True).values(
            'roleid__departmentid__departmentname'
        ).annotate(user_count=Count('employeeid')).order_by('roleid__departmentid__departmentname')
        role_breakdown = User.objects.filter(isactive=True).values(
            'roleid__accessid__accessid', 'roleid__accessid__accessrole'
        ).annotate(user_count=Count('employeeid')).order_by('roleid__accessid__accessid')
        maintenance_submitted = MainHeader.objects.filter(
            submittedat__year=today.year, submittedat__month=today.month
        ).count()
        maintenance_completed = MainHeader.objects.filter(
            overallstatus='Completed', completedat__year=today.year, completedat__month=today.month
        ).count()
        maintenance_pending = MainHeader.objects.filter(
            overallstatus__in=['Submitted', 'In Progress']
        ).count()
        ops_submitted = OperationsHeader.objects.filter(
            submittedat__year=today.year, submittedat__month=today.month
        ).count()
        ops_completed = OperationsHeader.objects.filter(
            overallstatus='Completed', ohapprovedat_capt__year=today.year, ohapprovedat_capt__month=today.month
        ).count()
        return render(request, 'users/profile.html', {
            'today': today,
            'total_active': total_active,
            'total_inactive': total_inactive,
            'dept_breakdown': dept_breakdown,
            'role_breakdown': role_breakdown,
            'maintenance_submitted': maintenance_submitted,
            'maintenance_completed': maintenance_completed,
            'maintenance_pending': maintenance_pending,
            'ops_submitted': ops_submitted,
            'ops_completed': ops_completed,
        })

    elif al == 3:  # Supervisor
        direct_reports = User.objects.filter(supervisorid=user)
        pending_maintenance = MainHeader.objects.filter(employeeid__in=direct_reports, overallstatus__in=['Submitted', 'In Progress']).count()
        pending_business = BusinessHeader.objects.filter(employeeid__in=direct_reports, overallstatus__in=['Submitted', 'In Progress']).count()
        revision_count = (
            MainHeader.objects.filter(employeeid__in=direct_reports, overallstatus='Revision Required').count() +
            BusinessHeader.objects.filter(employeeid__in=direct_reports, overallstatus='Revision Required').count()
        )
        completed_month = (
            MainHeader.objects.filter(employeeid__in=direct_reports, overallstatus='Completed', completedat__year=today.year, completedat__month=today.month).count() +
            BusinessHeader.objects.filter(employeeid__in=direct_reports, overallstatus='Completed', completedat__year=today.year, completedat__month=today.month).count()
        )

        return render(request, 'users/profile.html', {
            'today': today,
            'pending_maintenance': pending_maintenance,
            'pending_business': pending_business,
            'revision_count': revision_count,
            'completed_month': completed_month,
            **_leave_balance_context(user, today.year),
        })

    elif al == 2:  # Superintendent
        direct_reports = User.objects.filter(supervisorid=user)
        personal_pending = BusinessHeader.objects.filter(
            employeeid__in=direct_reports, overallstatus__in=['Submitted', 'In Progress']
        ).count()
        personal_completed = BusinessHeader.objects.filter(
            employeeid__in=direct_reports, overallstatus='Completed',
            completedat__year=today.year, completedat__month=today.month
        ).count()
        # Crew Daily Sheets, mine-wide (not scoped to direct-report Captains —
        # an unclaimed Submitted sheet has no approver yet to scope by, and
        # this matches superintendent_ops_daily, the only other place this
        # data gets browsed). Scoped by shiftdate, not approval date: a sheet
        # worked on Oct 31 but approved Nov 1 is October's work, not
        # November's — scoping by approval date instead used to misfile it
        # into the wrong month entirely (and, going through the shifter's own
        # supervisorid to get there, undercounted besides, since that field
        # is usually unset for shifters — they're organized by crew/basket).
        ops_logged_month = OperationsHeader.objects.filter(
            shiftdate__year=today.year, shiftdate__month=today.month,
        ).exclude(overallstatus='Draft').count()
        ops_completed_month = OperationsHeader.objects.filter(
            shiftdate__year=today.year, shiftdate__month=today.month,
            overallstatus='Completed',
        ).count()
        # Stragglers: Completed this month, but for a shift from an earlier
        # month — not folded into the two counts above (that would make them
        # mean two different things depending on timing), surfaced instead as
        # a small separate note so a late approval doesn't look like this
        # month's pace sagging.
        ops_stragglers_month = OperationsHeader.objects.filter(
            overallstatus='Completed',
            ohapprovedat_capt__year=today.year,
            ohapprovedat_capt__month=today.month,
        ).exclude(shiftdate__year=today.year, shiftdate__month=today.month).count()

        # Workforce headcount — active Shifters (al=5, Spare Shifters included)
        # and active Miners (al=8), mine-wide, not scoped to direct reports.
        total_shifters = User.objects.filter(roleid__accessid__accessid=5, isactive=True).count()
        total_miners = User.objects.filter(roleid__accessid__accessid=8, isactive=True).count()

        # My Team — headcount of this Superintendent's own direct reports
        # (Captains, plus everyone else who reports straight to them:
        # Supervisors, Business Employees, etc.), separate from the mine-wide
        # Workforce numbers above.
        active_direct_reports = direct_reports.filter(isactive=True)
        direct_captains = active_direct_reports.filter(roleid__accessid__accessid=4).count()
        direct_other_employees = active_direct_reports.exclude(roleid__accessid__accessid=4).count()

        return render(request, 'users/profile.html', {
            'today': today,
            'personal_pending': personal_pending,
            'personal_completed': personal_completed,
            'ops_logged_month': ops_logged_month,
            'ops_completed_month': ops_completed_month,
            'ops_stragglers_month': ops_stragglers_month,
            'total_shifters': total_shifters,
            'total_miners': total_miners,
            'direct_captains': direct_captains,
            'direct_other_employees': direct_other_employees,
        })

    elif al == 4:  # Mine Captain
        draft_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        awaiting_count = BusinessHeader.objects.filter(employeeid=user, overallstatus__in=['Submitted', 'In Progress']).count()
        revision_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Revision Required').count()
        latest_paid = BusinessHeader.objects.filter(employeeid=user, paidat__isnull=False).order_by('-paidat').first()
        paid_hours = BusinessEntry.objects.filter(businessheaderid=latest_paid).aggregate(Sum('hoursworked'))['hoursworked__sum'] if latest_paid else None
        paid_period = f"{_month_name[latest_paid.periodmonth]} {latest_paid.periodyear}" if latest_paid else None
        # Crew daily sheets are claim-model owned, same as Shifters' personal
        # timesheets — any captain can see an unclaimed Submitted sheet, and
        # a claimed one belongs to whichever captain claimed it, regardless
        # of the shifter's own supervisorid (which may not even be set).
        # Mirrors ops_approval_inbox's three buckets exactly.
        ops_pending_captain = OperationsHeader.objects.filter(
            overallstatus='Submitted'
        ).filter(
            Q(ohapprovedby_capt__isnull=True) | Q(ohapprovedby_capt=user)
        ).count()
        ops_revision_captain = OperationsHeader.objects.filter(
            overallstatus='Revision Required', ohapprovedby_capt=user
        ).count()
        ops_completed_month = OperationsHeader.objects.filter(
            overallstatus='Completed',
            ohapprovedby_capt=user,
            ohapprovedat_capt__year=today.year,
            ohapprovedat_capt__month=today.month,
        ).count()

        # Shifters' personal Business timesheets awaiting this captain's claim-
        # based review — mirrors business_approval_inbox's al=4 ownership
        # query exactly (any non-Shifter direct report, plus any Shifter
        # submission that's unclaimed or already claimed by this captain).
        business_subordinates = User.objects.filter(supervisorid=user).exclude(roleid__accessid__accessid=5)
        shifter_ownership = Q(employeeid__in=business_subordinates) | (
            Q(employeeid__roleid__accessid__accessid=5) &
            (Q(bh_approvedby_capt__isnull=True) | Q(bh_approvedby_capt=user))
        )
        shifters_pending = BusinessHeader.objects.filter(
            Q(overallstatus__in=['Submitted', 'In Progress']), shifter_ownership
        ).distinct().count()
        shifters_revision = BusinessHeader.objects.filter(
            Q(overallstatus='Revision Required'), shifter_ownership
        ).distinct().count()
        # Unlike the pending/revision buckets above, "completed" isn't a
        # claimable-queue concept — crediting it to this captain requires
        # they actually did it, not just that nobody else has claimed it yet.
        completed_ownership = Q(employeeid__in=business_subordinates) | Q(
            employeeid__roleid__accessid__accessid=5, bh_approvedby_capt=user,
        )
        shifters_completed_month = BusinessHeader.objects.filter(
            Q(overallstatus='Completed', completedat__year=today.year, completedat__month=today.month),
            completed_ownership,
        ).distinct().count()

        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'awaiting_count': awaiting_count,
            'revision_count': revision_count,
            'paid_hours': paid_hours,
            'paid_period': paid_period,
            'ops_pending_captain': ops_pending_captain,
            'ops_revision_captain': ops_revision_captain,
            'ops_completed_month': ops_completed_month,
            'shifters_pending': shifters_pending,
            'shifters_revision': shifters_revision,
            'shifters_completed_month': shifters_completed_month,
            **_leave_balance_context(user, today.year),
        })

    elif al == 5:  # Shifter
        is_contract_shifter = user.employmenttype == 'Contract'
        draft_count = awaiting_count = revision_count = None
        pay_history_pending = pay_history_paid_month = None
        paid_hours = paid_period = None

        if is_contract_shifter:
            pay_history_pending = OperationsEntry.objects.filter(
                employeeid=user, opsheaderid__overallstatus='Completed',
                linestatus='Approved', paidat__isnull=True,
            ).count()
            pay_history_paid_month = OperationsEntry.objects.filter(
                employeeid=user, paidat__year=today.year, paidat__month=today.month,
            ).count()
            latest_paid_entry = OperationsEntry.objects.filter(
                employeeid=user, paidat__isnull=False,
            ).select_related('opsheaderid').order_by('-paidat').first()
            if latest_paid_entry:
                paid_hours = latest_paid_entry.hoursworked
                paid_period = f"{_month_name[latest_paid_entry.opsheaderid.shiftdate.month]} {latest_paid_entry.opsheaderid.shiftdate.year}"
        else:
            draft_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
            awaiting_count = BusinessHeader.objects.filter(employeeid=user, overallstatus__in=['Submitted', 'In Progress']).count()
            revision_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Revision Required').count()
            latest_paid = BusinessHeader.objects.filter(employeeid=user, paidat__isnull=False).order_by('-paidat').first()
            paid_hours = BusinessEntry.objects.filter(businessheaderid=latest_paid).aggregate(Sum('hoursworked'))['hoursworked__sum'] if latest_paid else None
            paid_period = f"{_month_name[latest_paid.periodmonth]} {latest_paid.periodyear}" if latest_paid else None

        ops_draft = OperationsHeader.objects.filter(shifterid=user, overallstatus='Draft').count()
        ops_awaiting_review = OperationsHeader.objects.filter(shifterid=user, overallstatus__in=['Submitted', 'In Progress']).count()
        ops_revision = OperationsHeader.objects.filter(shifterid=user, overallstatus='Revision Required').count()
        ops_completed = OperationsHeader.objects.filter(shifterid=user, overallstatus='Completed', ohapprovedat_capt__year=today.year, ohapprovedat_capt__month=today.month).count()

        return render(request, 'users/profile.html', {
            'today': today,
            'is_contract_shifter': is_contract_shifter,
            'draft_count': draft_count,
            'awaiting_count': awaiting_count,
            'revision_count': revision_count,
            'pay_history_pending': pay_history_pending,
            'pay_history_paid_month': pay_history_paid_month,
            'paid_hours': paid_hours,
            'paid_period': paid_period,
            'ops_draft': ops_draft,
            'ops_awaiting_review': ops_awaiting_review,
            'ops_revision': ops_revision,
            'ops_completed': ops_completed,
            **_leave_balance_context(user, today.year),
        })
    
    elif al == 7:  # Payroll
        # Maintenance (MainHeader) — must have at least one approved entry to match unprocessed list
        maintenance_pending = MainHeader.objects.filter(
            overallstatus='Completed', paidat__isnull=True,
        ).annotate(
            approved_count=Count('mainentry', filter=Q(mainentry__linestatus='Approved'))
        ).filter(approved_count__gt=0).count()
        maintenance_paid_month = MainHeader.objects.filter(
            paidat__year=today.year, paidat__month=today.month,
        ).count()

        # Operations (OperationsHeader / OperationsEntry)
        ops_unpaid_ids = OperationsEntry.objects.filter(
            linestatus='Approved', paidat__isnull=True,
        ).values_list('opsheaderid', flat=True).distinct()
        ops_pending = OperationsHeader.objects.filter(
            overallstatus='Completed', opsheaderid__in=ops_unpaid_ids,
        ).count()
        ops_paid_month = OperationsEntry.objects.filter(
            paidat__year=today.year, paidat__month=today.month,
        ).values('opsheaderid').distinct().count()

        # Business Unit (BusinessHeader)
        business_pending = BusinessHeader.objects.filter(
            overallstatus='Completed', paidat__isnull=True,
        ).count()
        business_paid_month = BusinessHeader.objects.filter(
            paidat__year=today.year, paidat__month=today.month,
        ).count()

        # Bonuses — crew (OperationsBonus) and captain/ad-hoc (EmployeeBonus)
        # only count once confirmed by the supervisor/superintendent side
        # ('Submitted'); drafts aren't payroll's to see yet.
        crew_bonus_pending = OperationsBonus.objects.filter(status='Submitted').count()
        employee_bonus_pending = EmployeeBonus.objects.filter(status='Submitted').count()

        return render(request, 'users/profile.html', {
            'today': today,
            'current_month': today.strftime('%B %Y'),
            'maintenance_pending': maintenance_pending,
            'maintenance_paid_month': maintenance_paid_month,
            'ops_pending': ops_pending,
            'ops_paid_month': ops_paid_month,
            'business_pending': business_pending,
            'business_paid_month': business_paid_month,
            'crew_bonus_pending': crew_bonus_pending,
            'employee_bonus_pending': employee_bonus_pending,
        })

    elif al == 6:  # Business Unit Employee
        draft_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        awaiting_count = BusinessHeader.objects.filter(employeeid=user, overallstatus__in=['Submitted', 'In Progress']).count()
        revision_count = BusinessHeader.objects.filter(employeeid=user, overallstatus='Revision Required').count()
        latest_paid = BusinessHeader.objects.filter(employeeid=user, paidat__isnull=False).order_by('-paidat').first()
        paid_hours = BusinessEntry.objects.filter(businessheaderid=latest_paid).aggregate(Sum('hoursworked'))['hoursworked__sum'] if latest_paid else None
        paid_period = f"{_month_name[latest_paid.periodmonth]} {latest_paid.periodyear}" if latest_paid else None

        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'awaiting_count': awaiting_count,
            'revision_count': revision_count,
            'paid_hours': paid_hours,
            'paid_period': paid_period,
            **_leave_balance_context(user, today.year),
        })

    else:  # Maintenance Crew (9) and anyone else
        draft_count = MainHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        awaiting_count = MainHeader.objects.filter(employeeid=user, overallstatus__in=['Submitted', 'In Progress']).count()
        revision_count = MainHeader.objects.filter(employeeid=user, overallstatus='Revision Required').count()
        latest_paid = MainHeader.objects.filter(employeeid=user, paidat__isnull=False).order_by('-paidat').first()
        paid_hours = MainEntry.objects.filter(mainheaderid=latest_paid).aggregate(Sum('hoursworked'))['hoursworked__sum'] if latest_paid else None
        paid_period = latest_paid.paidat.strftime('%B %Y') if latest_paid else None
        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'awaiting_count': awaiting_count,
            'revision_count': revision_count,
            'paid_hours': paid_hours,
            'paid_period': paid_period,
            **_leave_balance_context(user, today.year),
        })

@login_required(login_url='login')
def upload_profile_photo(request):
    if request.method == 'POST' and request.FILES.get('profile_photo'):
        profile_photo = request.FILES['profile_photo']
        ext = profile_photo.name.rsplit('.', 1)[-1].lower()

        if ext not in ['jpg', 'jpeg', 'png', 'webp']:
            messages.error(request, f'"{profile_photo.name}" was not uploaded — only JPG, PNG, or WEBP images are allowed.')
            return redirect('profile')

        # The extension alone is just a filename, not a guarantee — a renamed
        # text file would otherwise get saved and served as a broken "photo".
        # Pillow actually decodes the file to confirm it's a real image before
        # anything touches disk; any failure here (not an image, truncated,
        # corrupted) is treated the same as a disallowed file type.
        try:
            Image.open(profile_photo).verify()
        except (UnidentifiedImageError, OSError):
            messages.error(request, f'"{profile_photo.name}" was not uploaded — the file isn\'t a valid image.')
            return redirect('profile')
        profile_photo.seek(0)

        # Filename includes a timestamp so every upload gets a new URL —
        # a fixed filename meant re-uploads kept the old browser-cached image.
        old_path = request.user.profilepic
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S%f')
        filename = f"profile_{request.user.employeeid}_{timestamp}.{ext}"
        save_path = os.path.join(settings.MEDIA_ROOT, 'profile_photos', filename)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'wb+') as destination:
            for chunk in profile_photo.chunks():
                destination.write(chunk)

        request.user.profilepic = f"profile_photos/{filename}"
        request.user.save()

        if old_path:
            old_full_path = os.path.join(settings.MEDIA_ROOT, old_path)
            if os.path.isfile(old_full_path):
                os.remove(old_full_path)

    return redirect('profile')


@login_required(login_url='login')
def add_employee(request):
    if request.user.access_level != 1:
        return redirect('profile')

    if request.method == 'POST':
        employeeid   = request.POST.get('employeeid', '').strip()
        firstname    = request.POST.get('firstname', '').strip()
        lastname     = request.POST.get('lastname', '').strip()
        phonenumber  = request.POST.get('phonenumber', '').strip()
        roleid       = request.POST.get('roleid', '').strip()
        supervisorid = request.POST.get('supervisorid', '').strip() or None
        hasaccess    = request.POST.get('hasaccess') == 'on'
        shiftertype  = request.POST.get('shiftertype', '').strip() or None
        crewid       = request.POST.get('crewid', '').strip() or None
        employmenttype = request.POST.get('employmenttype', 'Staff').strip() or 'Staff'
        contractid   = request.POST.get('contractid', '').strip() or None
        accountid    = request.POST.get('accountid', '').strip() or None
        hiredate     = request.POST.get('hiredate', '').strip() or None
        minerlevel   = _level_from_post(request.POST.get('minerlevel'))
        if minerlevel is None:
            contractid = None

        add_conflict = _basket_conflict(
            crewid, shiftertype,
            Roles.objects.filter(pk=roleid or None, accessid__accessid=5).exists(),
        )
        if User.objects.filter(employeeid=employeeid).exists():
            messages.error(request, f"Employee ID '{employeeid}' already exists.")
        elif not all([employeeid, firstname, lastname, phonenumber, roleid]):
            messages.error(request, "All required fields must be filled.")
        elif add_conflict:
            messages.error(request, add_conflict)
        else:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            new_user = User(
                employeeid=employeeid,
                firstname=firstname,
                lastname=lastname,
                phonenumber=phonenumber,
                roleid_id=roleid,
                supervisorid_id=supervisorid,
                isactive=True,
                hasaccess=hasaccess,
                is_temporary=True,
                shiftertype=shiftertype,
                crewid_id=crewid,
                employmenttype=employmenttype,
                contractid_id=contractid,
                accountid_id=accountid,
                hiredate=hiredate,
                minerlevel=minerlevel,
            )
            new_user.set_password(temp_password)
            new_user.save()
            print(f"SMS to {phonenumber}: Temp password for {firstname} {lastname} is {temp_password}")
            messages.success(request, f"{firstname} {lastname} added successfully.")

    return redirect('user_list')


@login_required(login_url='login')
def edit_employee(request, employeeid):
    if request.user.access_level != 1:
        return redirect('profile')

    employee = get_object_or_404(User, employeeid=employeeid)

    if request.method == 'POST':
        new_employeeid = request.POST.get('employeeid', '').strip()
        firstname = request.POST.get('firstname', '').strip()
        lastname = request.POST.get('lastname', '').strip()
        phonenumber = request.POST.get('phonenumber', '').strip()
        email = request.POST.get('email', '').strip() or None
        roleid = request.POST.get('roleid', '').strip()
        supervisorid = request.POST.get('supervisorid', '').strip() or None
        shiftertype = request.POST.get('shiftertype', '').strip() or None
        crewid = request.POST.get('crewid', '').strip() or None
        hasaccess = request.POST.get('hasaccess') == 'on'
        employmenttype = request.POST.get('employmenttype', 'Staff').strip() or 'Staff'
        contractid = request.POST.get('contractid', '').strip() or None
        accountid = request.POST.get('accountid', '').strip() or None
        hiredate = request.POST.get('hiredate', '').strip() or None
        terminationdate = request.POST.get('terminationdate', '').strip() or None
        minerlevel = _level_from_post(request.POST.get('minerlevel'))
        if minerlevel is None:
            contractid = None

        # A Shifter's own CrewAssignment rows are only reachable through
        # crew_assignment_detail while roleid still resolves to al=5 — moving
        # them to any other access level while they still run an active basket
        # would leave that basket's roster pointing at someone nobody can
        # manage anymore. Block it instead of silently orphaning the basket.
        new_role = Roles.objects.filter(pk=roleid).first() if roleid else None
        stranded_basket = (
            employee.access_level == 5
            and new_role and new_role.accessid_id != 5
            and CrewAssignment.objects.filter(shifter=employee, enddate__isnull=True).exists()
        )

        edit_conflict = _basket_conflict(
            crewid, shiftertype,
            bool(new_role and new_role.accessid_id == 5),
            exclude=employee,
        )
        if not all([new_employeeid, firstname, lastname, phonenumber, roleid]):
            messages.error(request, "All required fields must be filled.")
        elif User.objects.exclude(eid=employee.eid).filter(employeeid=new_employeeid).exists():
            messages.error(request, f"Employee ID '{new_employeeid}' is already in use.")
        elif edit_conflict:
            messages.error(request, edit_conflict)
        elif supervisorid == str(employee.eid):
            messages.error(request, "An employee cannot supervise themselves.")
        elif stranded_basket:
            messages.error(
                request,
                f"{employee.firstname} {employee.lastname} still runs an active basket — "
                f"transfer it to another shifter (Crew Assignments) before changing their role."
            )
        else:
            employee.employeeid = new_employeeid
            employee.firstname = firstname
            employee.lastname = lastname
            employee.phonenumber = phonenumber
            employee.email = email
            employee.roleid_id = roleid
            employee.supervisorid_id = supervisorid
            employee.shiftertype = shiftertype
            employee.crewid_id = crewid
            employee.hasaccess = hasaccess
            employee.employmenttype = employmenttype
            employee.contractid_id = contractid
            employee.accountid_id = accountid
            employee.hiredate = hiredate
            employee.terminationdate = terminationdate
            employee.minerlevel = minerlevel
            employee.save()
            messages.success(request, f"{firstname} {lastname} updated successfully.")

    return redirect('user_list')


@login_required(login_url='login')
def replace_employee(request, employeeid):
    if request.user.access_level != 1:
        return redirect('profile')

    leaving = get_object_or_404(User, employeeid=employeeid)
    subordinates = User.objects.filter(supervisorid=leaving, isactive=True)
    is_shifter = leaving.access_level == 5
    active_crew = CrewAssignment.objects.filter(
        shifter=leaving, enddate__isnull=True
    ).select_related('employee') if is_shifter else []

    error = None

    if request.method == 'POST':
        new_id = request.POST.get('new_employeeid', '').strip()
        firstname = request.POST.get('firstname', '').strip()
        lastname = request.POST.get('lastname', '').strip()
        phone = request.POST.get('phonenumber', '').strip()
        transfer_crew = request.POST.get('transfer_crew') == 'on'

        if User.objects.filter(employeeid=new_id).exists():
            error = f"Employee ID '{new_id}' already exists."
        elif not all([new_id, firstname, lastname, phone]):
            error = "All fields are required."
        else:
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            new_hire = User(
                employeeid=new_id,
                firstname=firstname,
                lastname=lastname,
                phonenumber=phone,
                roleid=leaving.roleid,
                supervisorid=leaving.supervisorid,
                isactive=True,
                hasaccess=True,
                is_temporary=True,
                shiftertype=leaving.shiftertype,
                crewid=leaving.crewid,
            )
            new_hire.set_password(temp_password)
            new_hire.save()

            print(f"SMS to {phone}: Temp password for {firstname} {lastname} is {temp_password}")

            subordinates.update(supervisorid=new_hire)

            if is_shifter and transfer_crew:
                today = timezone.now().date()
                crew_qs = CrewAssignment.objects.filter(shifter=leaving, enddate__isnull=True)
                employee_ids = list(crew_qs.values_list('employee_id', flat=True))
                crew_qs.update(enddate=today, active_employee_key=None)
                CrewAssignment.objects.bulk_create([
                    CrewAssignment(shifter=new_hire, employee_id=emp_id, startdate=today)
                    for emp_id in employee_ids
                ])

            leaving.isactive = False
            leaving.save()

            return redirect('user_list')

    return render(request, 'replace_employee.html', {
        'leaving': leaving,
        'subordinates': subordinates,
        'subordinate_count': subordinates.count(),
        'is_shifter': is_shifter,
        'active_crew': active_crew,
        'crew_count': len(active_crew) if is_shifter else 0,
        'error': error,
    })


@login_required(login_url='login')
def pending_onboarding(request):
    if request.user.access_level != 1:
        return redirect('profile')

    today = timezone.now().date()

    # Granting login to someone already in the system (promoted or covering, or a Miner
    # the Superintendent added). Same temporary password and SMS as the generator.
    if request.method == 'POST' and request.POST.get('action') == 'grant_access':
        person = get_object_or_404(User, employeeid=request.POST.get('employeeid', ''), isactive=True, hasaccess=False)
        if not person.phonenumber:
            messages.error(request, f'{person.firstname} {person.lastname} has no phone number. Add one in User Management first.')
            return redirect('pending_onboarding')
        temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        person.set_password(temp_password)
        person.is_temporary = True
        person.hasaccess = True
        person.lastresetdate = timezone.now()
        person.save()
        log_action(request.user, 'Grant System Access', 'Employee', person.eid, {'hasaccess': False}, {'hasaccess': True})
        print(f"SMS to {person.phonenumber}: The temporary password for {person.firstname} {person.lastname} is {temp_password}")
        messages.success(request, f'Access granted to {person.firstname} {person.lastname}. Temporary password sent.')
        return redirect('pending_onboarding')

    if request.method == 'POST':
        action = request.POST.get('action')
        target = get_object_or_404(User, employeeid=request.POST.get('employeeid', ''), onboarding_status='pending')

        if action == 'activate':
            temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            target.set_password(temp_password)
            target.is_temporary = True
            target.isactive = True
            target.hasaccess = True
            target.onboarding_status = 'activated'
            target.onboarding_resolved_by = request.user
            target.onboarding_resolved_on = today
            target.save()
            home = _home_basket(target) if target.access_level == 5 else None
            if home:
                gone_home = Q(home_shifter__isnull=True) | Q(home_shifter__isactive=False) | ~Q(home_shifter__roleid__accessid__accessid=5)
                for cov in CrewCoverage.objects.filter(
                    basket=home, enddate__isnull=True
                ).filter(gone_home).select_related('covering_shifter', 'home_shifter'):
                    for warning in end_coverage(cov, today, request.user):
                        messages.warning(request, warning)
                CrewAssignment.objects.filter(
                    basket=home, shifter__isnull=True, enddate__isnull=True
                ).update(shifter=target)
            print(f"SMS to {target.phonenumber}: Temp password for {target.firstname} {target.lastname} is {temp_password}")
            log_action(request.user, 'Activate Onboarding', 'Employee', target.eid, None, {'onboarding_status': 'activated'})
            messages.success(request, f'{target.firstname} {target.lastname} activated. Temporary password sent.')

        elif action == 'reject':
            target.onboarding_status = 'rejected'
            target.onboarding_resolved_by = request.user
            target.onboarding_resolved_on = today
            target.isactive = False
            if target.access_level == 5:
                target.crewid = None
                target.shiftertype = None
            target.save()
            CrewAssignment.objects.filter(employee=target, enddate__isnull=True).update(enddate=today, active_employee_key=None)
            log_action(request.user, 'Reject Onboarding', 'Employee', target.eid, None, {'onboarding_status': 'rejected'})
            messages.success(request, f'{target.firstname} {target.lastname} rejected. Their seat has been freed.')

        return redirect('pending_onboarding')

    pending = list(
        User.objects.filter(onboarding_status='pending')
        .select_related('roleid', 'onboarding_requested_by', 'crewid')
        .order_by('onboarding_requested_on', 'lastname', 'firstname')
    )
    active_by_employee = {}
    for a in CrewAssignment.objects.filter(enddate__isnull=True, employee__in=pending).select_related('basket__crew', 'basket__group', 'basket__discipline', 'positionid'):
        active_by_employee.setdefault(a.employee_id, []).append(a)
    for p in pending:
        p.placements = [
            ' — '.join(filter(None, [
                a.basket.unit_name if a.basket_id else None,
                a.basket.discipline.name if a.basket_id else None,
                a.positionid.positionname if a.positionid else None,
            ])) or 'Unplaced'
            for a in active_by_employee.get(p.eid, [])
        ]
        home = _home_basket(p) if p.access_level == 5 else None
        if home:
            p.placements.insert(0, f'Leads Crew {home.unit_name} — {home.discipline.name}')

    resolved = User.objects.filter(onboarding_status__in=['activated', 'rejected'])
    month_values = [d.strftime('%Y-%m') for d in resolved.dates('onboarding_resolved_on', 'month', order='DESC')]
    selected_month = request.GET.get('month')
    if selected_month not in month_values:
        selected_month = month_values[0] if month_values else None
    archive = []
    if selected_month:
        year, month = map(int, selected_month.split('-'))
        archive = list(
            resolved.filter(onboarding_resolved_on__year=year, onboarding_resolved_on__month=month)
            .select_related('roleid', 'onboarding_resolved_by')
            .order_by('-onboarding_resolved_on', 'lastname')
        )

    # Access requests: shifters (promoted, or covering as Spare Shifters) with no login yet.
    access_requests = User.objects.filter(
        isactive=True, hasaccess=False, roleid__accessid__accessid=5,
    ).exclude(onboarding_status='pending').select_related('roleid').order_by('lastname', 'firstname')
    # Information only: Miners the Superintendent added, who don't need login until promoted or covering.
    no_login_miners = User.objects.filter(
        isactive=True, hasaccess=False, roleid__accessid__accessid=8, onboarding_requested_by__isnull=False,
    ).select_related('onboarding_requested_by').order_by('lastname', 'firstname')

    return render(request, 'pending_onboarding.html', {
        'access_requests': access_requests,
        'no_login_miners': no_login_miners,
        'pending': pending,
        'archive': archive,
        'month_values': month_values,
        'selected_month': selected_month,
    })


EXIT_FILL_UNCOVERED = ('cover_temp', 'promote', 'assign', 'hire')
EXIT_FILL_COVERED = ('make_permanent', 'hire')


def _leave_member_seats(person):
    seats = list(CrewAssignment.objects.filter(employee=person, enddate__isnull=True))
    CrewAssignment.objects.filter(pk__in=[seat.pk for seat in seats]).update(enddate=timezone.now().date(), active_employee_key=None)
    return seats


def _coverage_overlaps(crew, shiftertype, start, end=None):
    """A coverage on this basket that is still open or ends after start. Ending on the day a new one starts is a handover, not an overlap."""
    basket = basket_for(crew, shiftertype)
    if basket is None:
        return False
    existing = CrewCoverage.objects.filter(basket=basket).filter(
        Q(enddate__isnull=True) | Q(enddate__gt=start)
    )
    if end:
        existing = existing.filter(startdate__lte=end)
    return existing.exists()


def _basket_crew(basket):
    # The Crews row a basket is filed under: the crew itself, or the joint crew row for a group.
    if basket.crew_id:
        return basket.crew
    return Crews.objects.filter(crewname=basket.group.groupname).first()


def _exit_fill_required(target):
    """Baskets target leaves leaderless that still have members: [(crew, shiftertype, coverage)]."""
    if target.access_level != 5:
        return []

    def has_members(basket):
        return basket is not None and CrewAssignment.objects.filter(basket=basket, enddate__isnull=True).exists()

    result = []
    covering = CrewCoverage.objects.filter(covering_shifter=target, enddate__isnull=True).select_related('basket').first()
    if covering and not covering.home_shifter_id:
        if has_members(covering.basket):
            result.append((_basket_crew(covering.basket), covering.basket.discipline.name, None))
    elif not covering:
        cov = CrewCoverage.objects.filter(home_shifter=target, enddate__isnull=True).select_related('basket').first()
        if cov:
            if has_members(cov.basket):
                result.append((_basket_crew(cov.basket), cov.basket.discipline.name, cov))
        else:
            home = _home_basket(target)
            if has_members(home):
                result.append((_basket_crew(home), home.discipline.name, None))

    seen = {(crew.crewid, st) for crew, st, _ in result}
    if covering and covering.basket_id:
        seen.add((_basket_crew(covering.basket).crewid, covering.basket.discipline.name))
    other_baskets = set(BasketShifter.objects.filter(shifter=target, is_home=False, enddate__isnull=True).values_list('basket_id', flat=True))
    other_baskets |= set(CrewAssignment.objects.filter(shifter=target, enddate__isnull=True, basket__isnull=False).values_list('basket_id', flat=True))
    for basket in UnitDiscipline.objects.filter(pk__in=other_baskets).select_related('crew', 'group', 'discipline').order_by('pk'):
        crew, st = _basket_crew(basket), basket.discipline.name
        if (crew.crewid, st) in seen:
            continue
        if has_members(basket):
            result.append((crew, st, None))
            seen.add((crew.crewid, st))
    return result


def _read_exit_fill(request, target):
    """Validates the fill choice before anything changes. Returns (fill, error)."""
    required = _exit_fill_required(target)
    if not required:
        return None, None
    if len(required) > 1:
        return None, f'{target.firstname} {target.lastname} runs more than one basket with members. Transfer one of them first, then record this.'
    crew, shiftertype, cov = required[0]
    kind = request.POST.get('fill_kind', '')
    if kind not in (EXIT_FILL_COVERED if cov else EXIT_FILL_UNCOVERED):
        return None, f'{target.firstname} {target.lastname} leads a basket with members. Choose who runs it next.'
    fill = {'kind': kind, 'crew': crew, 'shiftertype': shiftertype, 'cov': cov}
    employeeid = request.POST.get('fill_employee_id', '').strip()
    if kind == 'cover_temp':
        person = User.objects.filter(employeeid=employeeid, roleid__accessid__accessid=8, minerlevel__levelcode__in=['Lead', '1', '2'], isactive=True).first()
        if not person:
            return None, 'Pick a Lead, 1, or 2 Miner for temporary cover.'
    elif kind == 'promote':
        person = User.objects.filter(employeeid=employeeid, roleid__accessid__accessid=8, isactive=True).first()
        if not person:
            return None, 'Pick a Miner to promote.'
    elif kind == 'assign':
        homed = BasketShifter.objects.filter(is_home=True, enddate__isnull=True).values_list('shifter_id', flat=True)
        person = User.objects.filter(employeeid=employeeid, roleid__accessid__accessid=5, isactive=True).exclude(pk__in=homed).exclude(pk=target.pk).first()
        if not person:
            return None, 'Pick a shifter who is not already running a basket.'
    elif kind == 'make_permanent':
        person = cov.covering_shifter
    else:
        new = {k: request.POST.get(k, '').strip() for k in ('new_employeeid', 'new_firstname', 'new_lastname', 'new_phonenumber')}
        if not all(new.values()):
            return None, 'All fields are required to hire a new shifter.'
        if User.objects.filter(employeeid=new['new_employeeid']).exists():
            return None, f"Employee ID '{new['new_employeeid']}' already exists."
        fill['new'] = new
        return fill, None
    fill['employee'] = person
    return fill, None


def _apply_exit_fill(actor, fill, today):
    kind, crew, shiftertype = fill['kind'], fill['crew'], fill['shiftertype']
    if kind == 'hire':
        shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
        new = fill['new']
        hire = User(
            employeeid=new['new_employeeid'], firstname=new['new_firstname'], lastname=new['new_lastname'],
            phonenumber=new['new_phonenumber'], roleid=shifter_role, crewid=crew, shiftertype=shiftertype,
            isactive=False, hasaccess=True, is_temporary=True,
            onboarding_status='pending', onboarding_requested_by=actor, onboarding_requested_on=today,
        )
        hire.set_unusable_password()
        hire.save()
        log_action(actor, 'Hire Pending Shifter', 'Employee', hire.eid, None,
                   {'roleid': shifter_role.roleid, 'crewid': crew.crewid, 'shiftertype': shiftertype})
        return

    person = fill['employee']
    old_values = {'roleid': person.roleid_id, 'crewid': person.crewid_id, 'shiftertype': person.shiftertype}
    if kind == 'cover_temp':
        spare_role = get_object_or_404(Roles, rolename='Spare Shifter')
        person.roleid = spare_role
        person.crewid = crew
        person.shiftertype = shiftertype
        person.save(update_fields=['roleid', 'crewid', 'shiftertype', 'discipline'])
        CrewCoverage.objects.create(
            covering_shifter=person, home_shifter=None, crewid=crew, shiftertype=shiftertype,
            startdate=today, assignedby=actor,
        )
        log_action(actor, 'Promote to Spare Shifter', 'Employee', person.eid, old_values,
                   {'roleid': spare_role.roleid, 'crewid': crew.crewid, 'shiftertype': shiftertype})
    else:
        if kind in ('promote', 'make_permanent'):
            shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
            person.roleid = shifter_role
            _leave_member_seats(person)
            if kind == 'promote':
                person.minerlevel = _staff_level()
        person.crewid = crew
        person.shiftertype = shiftertype
        person.save()
        log_action(actor, 'Fill Basket on Exit', 'Employee', person.eid, old_values,
                   {'roleid': person.roleid_id, 'crewid': crew.crewid, 'shiftertype': shiftertype})
    CrewAssignment.objects.filter(
        basket=basket_for(crew, shiftertype), shifter__isnull=True, enddate__isnull=True
    ).update(shifter=person)


def _retire_shifter(actor, target, fill, today, quitting, minerlevel=None, contract=None):
    cov_as_home = CrewCoverage.objects.filter(home_shifter=target, enddate__isnull=True).select_related('covering_shifter', 'crewid').first()
    # Saved one by one (not a bulk update) so the basket table follows each lead's end.
    for lead in BasketLead.objects.filter(shifter=target, enddate__isnull=True):
        lead.enddate = today
        lead.save()

    old_values = {'isactive': target.isactive, 'roleid': target.roleid_id, 'crewid': target.crewid_id, 'shiftertype': target.shiftertype,
                  'minerlevel': _level_code(target.minerlevel), 'contractid': target.contractid_id}
    target.crewid = None
    target.shiftertype = None
    update_fields = ['crewid', 'shiftertype', 'discipline']
    if quitting:
        target.isactive = False
        target.terminationdate = today
        update_fields += ['isactive', 'terminationdate']
    else:
        target.roleid = get_object_or_404(Roles, rolename='Underground Mine Operator')
        target.minerlevel = minerlevel
        target.contractid = contract
        update_fields += ['roleid', 'minerlevel', 'contractid']
    target.save(update_fields=update_fields)

    for cov in CrewCoverage.objects.filter(covering_shifter=target, enddate__isnull=True).select_related('home_shifter', 'covering_shifter'):
        end_coverage(cov, today, actor, revert_role=False)

    if cov_as_home and ((fill and fill['kind'] == 'make_permanent') or not fill):
        end_coverage(cov_as_home, today, actor, revert_role=False)
    CrewAssignment.objects.filter(shifter=target, enddate__isnull=True).update(shifter=None)

    if quitting:
        CrewAssignment.objects.filter(employee=target, enddate__isnull=True).update(enddate=today, active_employee_key=None)

    if fill:
        _apply_exit_fill(actor, fill, today)

    action = 'Quit (Immediate)' if quitting else 'Demote to Miner (Permanent)'
    new_values = {'isactive': target.isactive, 'roleid': target.roleid_id, 'crewid': None, 'shiftertype': None}
    if not quitting:
        new_values['minerlevel'] = _level_code(minerlevel)
        new_values['contractid'] = contract.contractid if contract else None
    log_action(actor, action, 'Employee', target.eid, old_values, new_values)


def _basket_conflict(crewid, shiftertype, becoming_shifter, exclude=None):
    # Message if another active shifter already runs this crew and discipline
    # (as a home basket or a second-basket lead), else None. Called before any
    # write that gives a shifter a crew and discipline.
    if not becoming_shifter or not crewid or not shiftertype:
        return None
    basket = basket_for(Crews.objects.filter(pk=crewid).first(), shiftertype)
    if basket is None:
        return None
    row = BasketShifter.objects.filter(basket=basket, enddate__isnull=True).select_related('shifter').first()
    if row is None or (exclude is not None and row.shifter_id == exclude.pk):
        return None
    holder = row.shifter
    return f'Crew {basket.unit_name} {shiftertype} is already led by {holder.firstname} {holder.lastname}. Move or demote them first.'


def _basket_leaderless(crew, shiftertype):
    # No active shifter (home or second-basket lead), no seat with a shifter on it,
    # and no coverage on the basket.
    basket = basket_for(crew, shiftertype)
    if basket is None:
        return True
    if BasketShifter.objects.filter(basket=basket, enddate__isnull=True).exists():
        return False
    if CrewAssignment.objects.filter(basket=basket, shifter__isnull=False, enddate__isnull=True).exists():
        return False
    if CrewCoverage.objects.filter(basket=basket, enddate__isnull=True).exists():
        return False
    return True


def _basket_label(basket):
    # "Crew A — Production" for a basket row, read from the basket table.
    # A CrewAssignment can exist with no basket resolved (e.g. placed from
    # Unassigned before a crew/discipline was set) — "Unassigned" reads as a
    # real state there, where the old "Crew ? — ?" placeholder just looked
    # like broken data, especially next to a real position name in History.
    if basket is None:
        return 'Unassigned'
    return f'Crew {basket.unit_name} — {basket.discipline.name}'


def _home_basket(person):
    # The basket a shifter is home in (active, or pending IT access), or None.
    row = BasketShifter.objects.filter(shifter=person, is_home=True, enddate__isnull=True).select_related('basket').first()
    return row.basket if row else None


def _parse_basket(raw):
    crewid, _, shiftertype = (raw or '').partition(':')
    if not crewid or not shiftertype:
        return None, None
    return Crews.objects.filter(pk=crewid).first(), shiftertype


def _hand_over_basket(shifter, crew, shiftertype, today, assignedby):
    if _home_basket(shifter):
        # Already runs a basket — this is coverage, never a second permanent
        # lead. Only a new hire or a promoted Spare Shifter (or Miner, via
        # Transfer's own promote path) becomes someone's permanent second-
        # basket leader.
        CrewCoverage.objects.create(
            covering_shifter=shifter, home_shifter=None, crewid=crew, shiftertype=shiftertype,
            startdate=today, assignedby=assignedby,
        )
    else:
        shifter.crewid = crew
        shifter.shiftertype = shiftertype
        shifter.save(update_fields=['crewid', 'shiftertype', 'discipline'])


@login_required(login_url='login')
def crew_assignments(request):
    if request.user.access_level not in (1, 2):
        return redirect('profile')

    if request.method == 'POST' and request.POST.get('action') == 'quit_employee':
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid__in=[5, 8], isactive=True)
        today = timezone.now().date()
        fill, error = _read_exit_fill(request, target)
        if error:
            messages.error(request, error)
        else:
            _retire_shifter(request.user, target, fill, today, quitting=True)
            messages.success(request, f'{target.firstname} {target.lastname} recorded as quit as of {today:%b %d, %Y}.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'swap_baskets':
        a = User.objects.filter(employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=5, isactive=True).first()
        b = User.objects.filter(employeeid=request.POST.get('other_shifter_id', '').strip(), roleid__accessid__accessid=5, isactive=True).first()
        if not a or not b or a.pk == b.pk:
            messages.error(request, 'Pick a different shifter to swap baskets with.')
        elif not (_home_basket(a) and _home_basket(b)):
            messages.error(request, 'Both shifters need a home basket to swap.')
        elif CrewCoverage.objects.filter(enddate__isnull=True).filter(Q(home_shifter__in=[a, b]) | Q(covering_shifter__in=[a, b])).exists():
            messages.error(request, 'End any coverage on either basket before swapping.')
        elif BasketShifter.objects.filter(shifter__in=[a, b], is_home=False, enddate__isnull=True).exists():
            messages.error(request, 'One of them also leads a second basket. Transfer that basket first.')
        elif (CrewAssignment.objects.filter(shifter=a, enddate__isnull=True).exclude(basket=_home_basket(a)).exists()
              or CrewAssignment.objects.filter(shifter=b, enddate__isnull=True).exclude(basket=_home_basket(b)).exists()):
            messages.error(request, 'One of them also runs a second basket. Transfer that basket first.')
        else:
            a_ids = list(CrewAssignment.objects.filter(shifter=a, enddate__isnull=True).values_list('pk', flat=True))
            b_ids = list(CrewAssignment.objects.filter(shifter=b, enddate__isnull=True).values_list('pk', flat=True))
            a_old = (a.crewid_id, a.shiftertype)
            b_old = (b.crewid_id, b.shiftertype)
            with transaction.atomic():
                CrewAssignment.objects.filter(pk__in=a_ids).update(shifter=b)
                CrewAssignment.objects.filter(pk__in=b_ids).update(shifter=a)
                a.crewid_id, a.shiftertype = b_old
                b.crewid_id, b.shiftertype = a_old
                a.save(update_fields=['crewid', 'shiftertype', 'discipline'])
                b.save(update_fields=['crewid', 'shiftertype', 'discipline'])
                log_action(request.user, 'Swap Baskets', 'Employee', a.eid,
                           {'crewid': a_old[0], 'shiftertype': a_old[1]}, {'crewid': b_old[0], 'shiftertype': b_old[1]})
                log_action(request.user, 'Swap Baskets', 'Employee', b.eid,
                           {'crewid': b_old[0], 'shiftertype': b_old[1]}, {'crewid': a_old[0], 'shiftertype': a_old[1]})
            messages.success(request, f'{a.firstname} {a.lastname} and {b.firstname} {b.lastname} swapped baskets.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'move_position':
        crew, shiftertype = _parse_basket(request.POST.get('basket'))
        source = get_object_or_404(CrewAssignment, assignmentid=request.POST.get('source_assignment_id'), enddate__isnull=True)
        dest_position_id = request.POST.get('dest_position_id') or None
        dest_position_id = int(dest_position_id) if dest_position_id else None
        dest_basket = basket_for(crew, shiftertype) if crew and shiftertype else None
        if not crew or not shiftertype:
            messages.error(request, 'Select a basket to move this member into.')
        elif not _basket_leaderless(crew, shiftertype):
            messages.error(request, 'That basket has a leader now. Move the member onto its own shifter\'s position instead.')
        elif source.basket_id == getattr(dest_basket, 'pk', None) and source.positionid_id == dest_position_id:
            messages.warning(request, f'{source.employee.firstname} {source.employee.lastname} is already there.')
        else:
            today = timezone.now().date()
            old_values = {'crewid': source.crewid_id, 'shiftertype': source.shiftertype, 'positionid': source.positionid_id}
            source.enddate = today
            source.save(update_fields=['enddate'])
            CrewAssignment.objects.create(
                shifter=None, employee=source.employee, positionid_id=dest_position_id,
                startdate=today, crewid=crew, shiftertype=shiftertype,
                also_covers_basket=_carried_also_covers(source, dest_basket),
            )
            log_action(request.user, 'Move Crew Member', 'CrewAssignment', source.employee_id, old_values,
                       {'crewid': crew.crewid, 'shiftertype': shiftertype, 'positionid': dest_position_id})
            messages.success(request, f'Moved {source.employee.firstname} {source.employee.lastname} to the unassigned basket.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'hire_pending_shifter':
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        new_employeeid = request.POST.get('new_employeeid', '').strip()
        new_firstname = request.POST.get('new_firstname', '').strip()
        new_lastname = request.POST.get('new_lastname', '').strip()
        new_phone = request.POST.get('new_phonenumber', '').strip()
        basket = basket_for(Crews.objects.filter(pk=crewid).first() if crewid else None, shiftertype)
        basket_taken = basket is not None and (
            BasketShifter.objects.filter(basket=basket, enddate__isnull=True).exists()
            or CrewCoverage.objects.filter(basket=basket, enddate__isnull=True).exists()
        )
        if not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        elif basket_taken:
            messages.error(request, 'This basket already has a shifter or pending hire.')
        elif User.objects.filter(employeeid=new_employeeid).exists():
            messages.error(request, f"Employee ID '{new_employeeid}' already exists.")
        elif not all([new_employeeid, new_firstname, new_lastname, new_phone]):
            messages.error(request, 'All fields are required to hire a new shifter.')
        else:
            shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
            new_hire = User(
                employeeid=new_employeeid,
                firstname=new_firstname,
                lastname=new_lastname,
                phonenumber=new_phone,
                roleid=shifter_role,
                crewid_id=crewid,
                shiftertype=shiftertype,
                isactive=False,
                hasaccess=True,
                is_temporary=True,
                onboarding_status='pending',
                onboarding_requested_by=request.user,
                onboarding_requested_on=timezone.now().date(),
            )
            new_hire.set_unusable_password()
            new_hire.save()
            log_action(request.user, 'Hire Pending Shifter', 'Employee', new_hire.eid, None,
                       {'roleid': shifter_role.roleid, 'crewid': crewid, 'shiftertype': shiftertype})
            crew_name = Crews.objects.get(pk=crewid).crewname
            messages.success(
                request,
                f'{new_firstname} {new_lastname} hired as Shift Coordinator for Crew {crew_name} — {shiftertype}. '
                f"They'll run the basket once IT activates their access."
            )

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'assign_basket':
        # Fills a leaderless basket with an existing Shift Coordinator. A
        # shifter with no home basket at all takes this one on as their new
        # home, same as always. A shifter who already runs a basket can
        # never pick up a second one permanently — one person leads one
        # basket (a joint crew group is still one basket) — so this is
        # always coverage for them, exactly as temporary as Start Coverage.
        # A real permanent second lead only ever comes from a new hire or a
        # promoted Spare Shifter.
        shifter_id = request.POST.get('shifter_id', '').strip()
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        if not shifter_id:
            # A required <select> normally stops this client-side, but an
            # empty submission that still reaches the server (e.g. nothing
            # was eligible to list) used to 404 on get_object_or_404 instead
            # of saying anything.
            messages.error(request, 'Select a shifter to assign.')
        elif not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        else:
            target = get_object_or_404(User, employeeid=shifter_id, roleid__accessid__accessid=5, isactive=True)
            is_home_free = _home_basket(target) is None
            basket_crew = Crews.objects.get(pk=crewid)
            if not _basket_leaderless(basket_crew, shiftertype):
                messages.error(request, 'This basket already has a leader.')
                next_url = request.POST.get('next', '').strip()
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect('crew_grid')
            basket = basket_for(basket_crew, shiftertype)
            claimed = CrewAssignment.objects.filter(
                basket=basket, shifter__isnull=True, enddate__isnull=True
            ).update(shifter=target)
            if is_home_free:
                target.crewid_id = crewid
                target.shiftertype = shiftertype
                target.save(update_fields=['crewid', 'shiftertype', 'discipline'])
                verb = 'now runs'
            else:
                # Already runs a basket — this is coverage, never a second
                # permanent lead. Only a new hire or a promoted Spare Shifter
                # becomes someone's permanent second-basket leader.
                CrewCoverage.objects.create(
                    covering_shifter=target, home_shifter=None, crewid=basket_crew, shiftertype=shiftertype,
                    startdate=timezone.now().date(), assignedby=request.user,
                )
                verb = 'is now covering'
            log_action(request.user, 'Assign Shifter to Basket', 'Employee', target.eid,
                       {'crewid': None, 'shiftertype': None}, {'crewid': crewid, 'shiftertype': shiftertype})
            crew_name = basket_crew.crewname
            if claimed:
                messages.success(
                    request,
                    f'{target.firstname} {target.lastname} {verb} Crew {crew_name} — {shiftertype} '
                    f'({claimed} existing member{"s" if claimed != 1 else ""} picked up).'
                )
            else:
                messages.success(request, f'{target.firstname} {target.lastname} {verb} Crew {crew_name} — {shiftertype}.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'promote_and_assign_basket':
        # One-step "promote a Miner straight into this vacant basket" —
        # the Grid's version of promote_to_shifter_permanent, so a leaderless
        # basket can be filled by promoting from within the ranks without a
        # separate trip to Shifter/Miner Management.
        employee_id = request.POST.get('employee_id', '').strip()
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        if not employee_id:
            messages.error(request, 'Select a Miner to promote.')
        elif not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        else:
            target = get_object_or_404(User, employeeid=employee_id, roleid__accessid__accessid=8, isactive=True)
            shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
            target.roleid = shifter_role
            _leave_member_seats(target)
            target.minerlevel = _staff_level()
            target.crewid_id = crewid
            target.shiftertype = shiftertype
            target.save(update_fields=['roleid', 'minerlevel', 'crewid', 'shiftertype', 'discipline'])
            basket = basket_for(Crews.objects.filter(pk=crewid).first(), shiftertype)
            claimed = CrewAssignment.objects.filter(
                basket=basket, shifter__isnull=True, enddate__isnull=True
            ).update(shifter=target)
            log_action(request.user, 'Promote to Shifter (Permanent)', 'Employee', target.eid,
                       {'roleid': None, 'crewid': None, 'shiftertype': None},
                       {'roleid': shifter_role.roleid, 'crewid': crewid, 'shiftertype': shiftertype})
            crew_name = Crews.objects.get(pk=crewid).crewname
            messages.success(
                request,
                f'{target.firstname} {target.lastname} promoted to Shifter and now runs Crew {crew_name} — {shiftertype}'
                + (f' ({claimed} existing member{"s" if claimed != 1 else ""} picked up).' if claimed else '.')
            )

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'promote_and_assign_basket_temporary':
        employee_id = request.POST.get('employee_id', '').strip()
        crew = Crews.objects.filter(pk=request.POST.get('crewid') or None).first()
        shiftertype = request.POST.get('shiftertype') or None
        if not employee_id:
            messages.error(request, 'Select a Miner to cover temporarily.')
        elif not crew or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        elif not _basket_leaderless(crew, shiftertype):
            messages.error(request, 'This basket already has a leader.')
        else:
            target = get_object_or_404(
                User, employeeid=employee_id,
                roleid__accessid__accessid=8, minerlevel__levelcode__in=['Lead', '1', '2'], isactive=True,
            )
            _apply_exit_fill(request.user, {'kind': 'cover_temp', 'crew': crew, 'shiftertype': shiftertype, 'employee': target}, timezone.now().date())
            messages.success(request, f'{target.firstname} {target.lastname} is covering Crew {crew.crewname} — {shiftertype} temporarily.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'make_cover_permanent':
        today = timezone.now().date()
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=5, isactive=True)
        cov = CrewCoverage.objects.filter(covering_shifter=target, enddate__isnull=True).select_related('home_shifter', 'crewid').first()
        if not cov:
            messages.error(request, f'{target.firstname} {target.lastname} is not covering a basket.')
        elif cov.home_is_live:
            messages.error(request, f'{cov.home_shifter.firstname} {cov.home_shifter.lastname} is still an active shifter. Use Transfer to hand the basket over instead.')
        else:
            end_coverage(cov, today, request.user, revert_role=False)
            _apply_exit_fill(request.user, {'kind': 'make_permanent', 'crew': cov.basket_crew, 'shiftertype': cov.basket_shiftertype, 'employee': target}, today)
            messages.success(request, f'{target.firstname} {target.lastname} is now the permanent shifter for Crew {cov.basket_crew.crewname} — {cov.basket_shiftertype}.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'bulk_add_vacant_members':
        crew, shiftertype = _parse_basket(request.POST.get('basket'))
        start_date = request.POST.get('startdate')
        employee_ids = request.POST.getlist('employee_ids')
        if not crew or not shiftertype:
            messages.error(request, 'Select a crew and discipline.')
        elif not _basket_leaderless(crew, shiftertype):
            messages.error(request, 'This basket has a leader now. Add members from its shifter instead.')
        else:
            added = []
            basket = basket_for(crew, shiftertype)
            for employee_id in employee_ids:
                # Matches available_employees above: a Miner, or a Spare
                # Shifter currently covering a different basket — covering is
                # a leadership role elsewhere, not a member seat here.
                employee = get_object_or_404(
                    User, Q(roleid__accessid__accessid=8) | Q(roleid__rolename='Spare Shifter'),
                    employeeid=employee_id, isactive=True,
                )
                position_id = request.POST.get(f'position_{employee_id}') or None
                primary = basket_for(crew, shiftertype)
                also, also_error = _also_covers_basket(request, employee_id, primary)
                if also_error:
                    messages.error(request, also_error)
                    break
                CrewAssignment.objects.create(
                    shifter=None, employee=employee, positionid_id=position_id,
                    startdate=start_date, crewid=crew, shiftertype=shiftertype,
                    also_covers_basket=also,
                )
                added.append(f'{employee.firstname} {employee.lastname}')
            if added:
                messages.success(request, f'Added {len(added)} member{"s" if len(added) != 1 else ""} to Crew {crew.crewname} — {shiftertype}: {", ".join(added)}.')
            else:
                messages.warning(request, 'No members selected.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'edit_employee_level':
        # Level/Contract Code are attributes of the person, not the roster row
        # they currently occupy — this patches only the User record, no
        # CrewAssignment is touched, so it carries no move/replace semantics
        # (see Crew Grid's chip badge, which triggers this separately from
        # the Replace action on the same chip). Open to Miners and Shifters —
        # a promoted Spare Shifter keeps the minerlevel they carried as a
        # Miner (promotion only flips roleid), so the badge/modal need to
        # reach them at their current access level too.
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid__in=[5, 8], isactive=True)
        raw_level = request.POST.get('minerlevel', '').strip()
        raw_contractid = request.POST.get('contractid', '').strip()
        minerlevel = _level_from_post(raw_level)
        next_url = request.POST.get('next', '').strip()
        # _level_from_post also returns None for "-- Unclassified --" (a
        # deliberate clear), so a non-blank value that still failed to resolve
        # — a stale/tampered id — has to be caught separately, or it would
        # silently wipe the level instead of being rejected.
        # Same idea for the Contract: it's only offered under a Level, so a
        # mismatched or stale id (including one left over after the Level
        # above got cleared/changed) is rejected rather than saved or quietly dropped.
        contract = (
            Contract.objects.filter(pk=int(raw_contractid), levels=minerlevel, isactive=1).first()
            if (minerlevel and raw_contractid.isdigit()) else None
        )
        if raw_level and minerlevel is None:
            error = 'That level no longer exists — pick a current one.'
        elif raw_contractid and contract is None:
            error = "That contract isn't offered at the chosen level."
        else:
            error = None

        if error:
            messages.error(request, error)
        else:
            contractid = contract.contractid if contract else None
            old_values = {'minerlevel': _level_code(target.minerlevel), 'contractid': target.contractid_id}
            target.minerlevel = minerlevel
            target.contractid_id = contractid
            target.save(update_fields=['minerlevel', 'contractid'])
            log_action(request.user, 'Edit Level/Contract', 'Employee', target.eid,
                       old_values, {'minerlevel': _level_code(minerlevel), 'contractid': contractid})
            messages.success(request, f'Updated {target.firstname} {target.lastname}.')

        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'promote_to_shifter_permanent':
        # Permanent (not Spare) promotion — a deliberate placement decision,
        # so it lives here as its own explicit action rather than on the
        # Grid's drag/assign gestures, which stay scoped to fast, reversible
        # temporary coverage. Open to any Miner — unlike Spare Shifter
        # coverage, this isn't an emergency fill, so no Lead/1/2 floor.
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=8, isactive=True)
        shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
        old_values = {'roleid': target.roleid_id, 'minerlevel': _level_code(target.minerlevel)}
        target.roleid = shifter_role
        _leave_member_seats(target)
        # Staff/Contract is HR's classification, independent of role — but a
        # newly permanent Shifter is no longer working the Miner-level scale,
        # so it defaults to Staff and stays editable immediately afterward
        # via the Crew Grid's Level/Contract modal (already open to Shifters).
        target.minerlevel = _staff_level()
        target.save(update_fields=['roleid', 'minerlevel'])
        log_action(request.user, 'Promote to Shifter (Permanent)', 'Employee', target.eid,
                   old_values, {'roleid': shifter_role.roleid, 'minerlevel': 'Staff'})
        messages.success(request, f'{target.firstname} {target.lastname} permanently promoted to Shifter.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    if request.method == 'POST' and request.POST.get('action') == 'demote_to_miner_permanent':
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=5, isactive=True)
        today = timezone.now().date()
        # A demoted person returns as a Miner, so they need a real Miner Level
        # (Staff isn't one). The Contract is optional and must be offered under that Level.
        level = _level_from_post(request.POST.get('minerlevel'))
        contractid = request.POST.get('contractid', '').strip()
        contract = Contract.objects.filter(pk=int(contractid), levels=level, isactive=1).first() if (level and contractid.isdigit()) else None
        fill, error = _read_exit_fill(request, target)
        if not level or level.levelcode == 'Staff':
            messages.error(request, 'Choose a Miner level (Lead, 1, 2, 3 or 4) for the demoted person.')
        elif contractid and contract is None:
            messages.error(request, 'That contract is not offered at the chosen level.')
        elif error:
            messages.error(request, error)
        else:
            _retire_shifter(request.user, target, fill, today, quitting=False, minerlevel=level, contract=contract)
            messages.success(request, f'{target.firstname} {target.lastname} demoted to Miner.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_grid')

    return redirect('crew_grid')



@login_required(login_url='login')
def position_catalog(request):
    if request.user.access_level not in (1, 2):
        return redirect('profile')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            positionname = request.POST.get('positionname', '').strip()
            shiftertype = request.POST.get('shiftertype', '').strip() or None
            sortorder = int(request.POST['sortorder']) if request.POST.get('sortorder', '').lstrip('-').isdigit() else 0
            if positionname:
                Position.objects.create(positionname=positionname, shiftertype=shiftertype, isactive=1, sortorder=sortorder)
                messages.success(request, f'Added position: {positionname}.')
            else:
                messages.error(request, 'Position name is required.')
            next_url = request.POST.get('next', '').strip()
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('position_catalog')

        elif action == 'bulk_classify':
            updated = 0
            for position in Position.objects.all():
                shiftertype = request.POST.get(f'shiftertype_{position.positionid}') or None
                isactive = 1 if request.POST.get(f'isactive_{position.positionid}') == 'on' else 0
                sortorder = int(request.POST.get(f'sortorder_{position.positionid}')) if request.POST.get(f'sortorder_{position.positionid}', '').lstrip('-').isdigit() else position.sortorder
                if position.shiftertype != shiftertype or position.isactive != isactive or position.sortorder != sortorder:
                    position.shiftertype = shiftertype
                    position.isactive = isactive
                    position.sortorder = sortorder
                    position.save(update_fields=['shiftertype', 'isactive', 'sortorder'])
                    updated += 1
            messages.success(request, f'Updated {updated} position{"s" if updated != 1 else ""}.' if updated else 'No changes to save.')
            return redirect('position_catalog')

    positions = list(Position.objects.select_related('discipline').order_by('sortorder', 'positionname'))
    # One group per discipline (in discipline order), then the unclassified positions.
    groups = [
        {'label': d.name, 'positions': [p for p in positions if p.discipline_id == d.pk]}
        for d in Discipline.objects.order_by('sortorder', 'name')
    ]
    groups.append({'label': 'Unclassified', 'positions': [p for p in positions if p.discipline_id is None]})
    return render(request, 'users/position_catalog.html', {
        'positions': positions,
        'groups': groups,
        'unclassified_count': sum(1 for p in positions if p.isactive and p.discipline_id is None),
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
    })


def management_sections():
    """Crew Management's crews and the sections (disciplines) each one runs, read
    from the unit links. Single crews come first (A, B, ...), then joint crews.
    Sections follow the discipline sort order."""
    sections = {}
    for link in UnitDiscipline.objects.select_related('crew', 'group', 'discipline').filter(discipline__isactive=1).order_by('discipline__sortorder', 'discipline__name'):
        sections.setdefault(link.unit_name, []).append(link.discipline.name)
    return dict(sorted(sections.items(), key=lambda item: (len(item[0]) > 1, item[0])))


def _assign_unassigned(request):
    # Places one unplaced person from the Crew Management overview. A Miner joins the
    # basket with a position (led baskets through their leader, leaderless ones unattached,
    # as the vacant-basket add does). A Shift Coordinator becomes the basket's leader, only
    # if the basket has none.
    person = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), isactive=True)
    name = f'{person.firstname} {person.lastname}'
    crew, section = _parse_basket(request.POST.get('basket'))
    if not crew or section not in management_sections().get(crew.crewname, []):
        messages.error(request, 'Choose a crew and discipline.')
        return redirect('crew_management')
    basket_label = f'Crew {crew.crewname} {section}'

    if person.access_level == 5:
        if _home_basket(person):
            messages.error(request, f'{name} already has a basket. Move them with Transfer or Swap instead.')
            return redirect('crew_management')
        if not _basket_leaderless(crew, section):
            messages.error(request, f'{basket_label} already has a leader.')
            return redirect('crew_management')
        conflict = _basket_conflict(crew.crewid, section, True, exclude=person)
        if conflict:
            messages.error(request, conflict)
            return redirect('crew_management')
        person.crewid = crew
        person.shiftertype = section
        person.save(update_fields=['crewid', 'shiftertype', 'discipline'])
        CrewAssignment.objects.filter(basket=basket_for(crew, section), shifter__isnull=True, enddate__isnull=True).update(shifter=person)
        log_action(request.user, 'Assign Leader', 'Employee', person.eid, None, {'crewid': crew.crewid, 'shiftertype': section})
        messages.success(request, f'{name} now leads {basket_label}.')
        return redirect('crew_management')

    if person.access_level != 8:
        messages.error(request, 'Only Miners and Shift Coordinators can be assigned here.')
        return redirect('crew_management')
    if CrewAssignment.objects.filter(employee=person, enddate__isnull=True).exists():
        messages.error(request, f'{name} is already placed in a basket.')
        return redirect('crew_management')
    position_id = request.POST.get('position', '').strip()
    position = Position.objects.filter(
        pk=int(position_id) if position_id.isdigit() else None, isactive=1,
    ).filter(Q(discipline__name=section) | Q(discipline__isnull=True)).first()
    if position is None:
        messages.error(request, f'Choose a position for {section}.')
        return redirect('crew_management')
    basket = basket_for(crew, section)
    leader_row = BasketShifter.objects.filter(
        basket=basket, enddate__isnull=True, shifter__isactive=True,
    ).select_related('shifter').first() if basket else None
    leader = leader_row.shifter if leader_row else None
    assignment = CrewAssignment.objects.create(
        shifter=leader, employee=person, positionid=position,
        startdate=request.POST.get('startdate') or timezone.now().date(),
        crewid=crew, shiftertype=section,
    )
    log_action(request.user, 'Assign Unassigned', 'CrewAssignment', assignment.assignmentid, None,
               {'employee': person.eid, 'crewid': crew.crewid, 'shiftertype': section, 'positionid': position.positionid})
    messages.success(request, f'{name} assigned to {basket_label} as {position.positionname}.')
    return redirect('crew_management')


def _add_miner(request):
    # Superintendent adds a hired Miner straight into the system, with no System Admin step.
    # A Miner has no login until they're promoted or covering, so access stays off and no
    # password is set. Employment is always Contract and the role is looked up by name.
    employeeid = request.POST.get('employee_id', '').strip()
    firstname = request.POST.get('firstname', '').strip()
    lastname = request.POST.get('lastname', '').strip()
    phone = request.POST.get('phonenumber', '').strip()
    level = _level_from_post(request.POST.get('minerlevel'))
    contract_raw = request.POST.get('contractid', '').strip()
    today = timezone.now().date()

    if not employeeid or not firstname or not lastname:
        messages.error(request, 'Employee ID, first name and last name are required.')
        return redirect('crew_management')
    if not level or level.levelcode == 'Staff':
        messages.error(request, 'Choose a Miner level.')
        return redirect('crew_management')
    contract = Contract.objects.filter(pk=int(contract_raw), levels=level, isactive=1).first() if contract_raw.isdigit() else None
    if contract is None:
        messages.error(request, 'Choose a contract offered at that level.')
        return redirect('crew_management')
    role = Roles.objects.filter(rolename='Underground Mine Operator').first()
    if role is None:
        messages.error(request, 'The Underground Mine Operator role is missing.')
        return redirect('crew_management')

    existing = User.objects.filter(employeeid=employeeid).first()
    if existing and (existing.isactive or existing.onboarding_status == 'pending'):
        messages.error(request, f'Employee ID {employeeid} is already in use.')
        return redirect('crew_management')
    if existing:
        # Rehire: the same record comes back, so there's no duplicate and their history stays.
        old_values = {'isactive': False, 'roleid': existing.roleid_id, 'minerlevel': _level_code(existing.minerlevel)}
        existing.firstname, existing.lastname = firstname, lastname
        existing.phonenumber = phone or existing.phonenumber
        existing.roleid = role
        existing.employmenttype = 'Contract'
        existing.minerlevel = level
        existing.contractid = contract
        existing.isactive = True
        existing.terminationdate = None
        existing.hasaccess = False
        existing.save()
        log_action(request.user, 'Rehire Miner (no system access)', 'Employee', existing.eid, old_values,
                   {'isactive': True, 'roleid': role.roleid, 'minerlevel': level.levelcode})
        messages.success(request, f'{firstname} {lastname} rehired as a Miner. They can be placed from Unassigned.')
        return redirect('crew_management')

    miner = User(
        employeeid=employeeid, firstname=firstname, lastname=lastname, phonenumber=phone,
        roleid=role, employmenttype='Contract', minerlevel=level, contractid=contract,
        isactive=True, hasaccess=False, is_temporary=False,
        onboarding_requested_by=request.user, onboarding_requested_on=today,
    )
    miner.set_unusable_password()
    miner.save()
    log_action(request.user, 'Add Miner (no system access)', 'Employee', miner.eid, None,
               {'employeeid': employeeid, 'minerlevel': level.levelcode, 'contractid': contract.contractid})
    messages.success(request, f'{firstname} {lastname} added as a Miner. They can be placed from Unassigned.')
    return redirect('crew_management')


def seat_problems(assignments):
    """Seats the Superintendent should fix: not on a basket, or whose position belongs to
    another discipline. Returns [(assignment, reason)]."""
    problems = []
    for a in assignments:
        if not a.basket_id:
            problems.append((a, 'Not linked to a basket yet (missing crew/discipline on the assignment).'))
            continue
        if a.positionid and a.positionid.discipline_id and a.positionid.discipline_id != a.basket.discipline_id:
            problems.append((a, f'Position is classified as {a.positionid.discipline.name}, but this assignment is filed under {a.basket.discipline.name}.'))
    return problems


@login_required(login_url='login')
def crew_management(request):
    # Overview of the six crews. Each crew expands into its sections, and each
    # section is a basket page. Unassigned Miners and pending hires sit below.
    if request.user.access_level not in (1, 2):
        return redirect('profile')

    if request.method == 'POST' and request.POST.get('action') == 'assign_unassigned':
        return _assign_unassigned(request)
    if request.method == 'POST' and request.POST.get('action') == 'add_miner':
        return _add_miner(request)

    sections = management_sections()
    crews = {c.crewname: c for c in Crews.objects.filter(isactive=1, crewname__in=sections.keys())}
    basket_by_key = {(b.unit_name, b.discipline.name): b for b in UnitDiscipline.objects.select_related('crew', 'group', 'discipline')}
    leader_by_basket = {}
    pending_by_basket = {}
    for row in BasketShifter.objects.filter(enddate__isnull=True).select_related('shifter'):
        if row.shifter.onboarding_status == 'pending':
            pending_by_basket.setdefault(row.basket_id, row.shifter)
        elif row.shifter.isactive:
            leader_by_basket.setdefault(row.basket_id, row.shifter)
    active = CrewAssignment.objects.filter(enddate__isnull=True).exclude(employee__isnull=True)

    crew_cards = []
    for name, crew_sections in sections.items():
        crew = crews.get(name)
        baskets = []
        for section in crew_sections:
            basket = basket_by_key.get((name, section))
            leader = leader_by_basket.get(basket.pk) if basket else None
            pending_leader = pending_by_basket.get(basket.pk) if basket and not leader else None
            members = active.filter(basket=basket).values('employee_id').distinct().count() if basket else 0
            baskets.append({'section': section, 'leader': leader, 'pending_leader': pending_leader, 'members': members})
        crew_cards.append({
            'name': name,
            'exists': crew is not None,
            'baskets': baskets,
            'total_members': sum(b['members'] for b in baskets),
            'leaderless': sum(1 for b in baskets if b['leader'] is None and b['pending_leader'] is None),
            'pending_leaders': sum(1 for b in baskets if b['pending_leader'] is not None),
        })

    rostered_ids = active.values_list('employee_id', flat=True)
    # Unplaced people: Miners with no seat, plus Shift Coordinators with no crew or discipline
    # (a shifter is normally hired onto a basket, so the second group is the rare case).
    # A covering Spare Shifter has no home crew, but they hold a seat and a cover, so they're placed.
    covering_ids = CrewCoverage.objects.filter(enddate__isnull=True).values_list('covering_shifter_id', flat=True)
    homed_ids = BasketShifter.objects.filter(is_home=True, enddate__isnull=True).values_list('shifter_id', flat=True)
    unassigned = User.objects.exclude(onboarding_status='pending').filter(
        Q(roleid__accessid__accessid=8, isactive=True) & ~Q(eid__in=rostered_ids)
        | Q(roleid__accessid__accessid=5, isactive=True) & ~Q(eid__in=homed_ids)
        & ~Q(eid__in=rostered_ids) & ~Q(eid__in=covering_ids)
    ).select_related('minerlevel', 'contractid', 'roleid').order_by('lastname', 'firstname')
    pending = User.objects.filter(onboarding_status='pending').select_related('roleid', 'crewid', 'onboarding_requested_by').order_by('lastname', 'firstname')

    # Search across everyone on the books: active Shifters and Miners, plus pending hires.
    # Each result says where the person sits and links to their basket when they have one.
    q = request.GET.get('q', '').strip()
    level = request.GET.get('level', '').strip()
    results = None
    if q or level:
        people = User.objects.filter(
            Q(isactive=True, roleid__accessid__accessid__in=[5, 8]) | Q(onboarding_status='pending')
        ).select_related('minerlevel', 'roleid', 'crewid')
        for token in q.split():
            people = people.filter(Q(firstname__icontains=token) | Q(lastname__icontains=token) | Q(employeeid__icontains=token))
        if level:
            people = people.filter(minerlevel__levelcode=level)
        seat_by_employee = {}
        for a in CrewAssignment.objects.filter(enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline'):
            seat_by_employee.setdefault(a.employee_id, a)
        home_by_shifter = {
            row.shifter_id: row.basket
            for row in BasketShifter.objects.filter(is_home=True, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline')
        }
        results = []
        for person in people.order_by('lastname', 'firstname')[:100]:
            seat = seat_by_employee.get(person.eid)
            if person.onboarding_status == 'pending':
                where, url = 'Pending IT access', None
            elif person.access_level == 5 and home_by_shifter.get(person.pk):
                home = home_by_shifter[person.pk]
                where = f'Leads Crew {home.unit_name} · {home.discipline.name}'
                url = reverse('crew_management_basket', args=[home.unit_name, home.discipline.name])
            elif seat and seat.basket_id:
                where = f'Crew {seat.basket.unit_name} · {seat.basket.discipline.name}'
                url = reverse('crew_management_basket', args=[seat.basket.unit_name, seat.basket.discipline.name])
            else:
                where, url = 'Unassigned', None
            results.append({'person': person, 'where': where, 'url': url})

    return render(request, 'users/crew_management.html', {
        'crew_cards': crew_cards,
        'active_captains': User.objects.filter(roleid__accessid__accessid=4, isactive=True).order_by('lastname', 'firstname'),
        'needs_attention': seat_problems(CrewAssignment.objects.filter(enddate__isnull=True).select_related('basket__discipline', 'positionid__discipline')),
        'unassigned': unassigned,
        'pending': pending,
        'q': q,
        'level': level,
        'results': results,
        'level_choices': MinerLevel.objects.all(),
        'basket_choices': [
            {'value': f'{crews[name].crewid}:{section}', 'label': f'Crew {name} — {section}', 'section': section}
            for name, crew_sections in sections.items() if name in crews
            for section in crew_sections
        ],
        **grid_action_data(),
        'minerlevel_choices': _miner_level_choices(),
    })


def _initials(person):
    return ((person.firstname[:1] or '') + (person.lastname[:1] or '')).upper() or '?'


@login_required(login_url='login')
def crew_management_crew(request, crewname):
    # One crew's sections: each card opens that basket's page.
    if request.user.access_level not in (1, 2):
        return redirect('profile')
    crew_sections = management_sections().get(crewname)
    if crew_sections is None:
        raise Http404
    crew = get_object_or_404(Crews, crewname=crewname, isactive=1)

    active = CrewAssignment.objects.filter(enddate__isnull=True, basket__isnull=False)
    sections = []
    for section in crew_sections:
        basket = basket_for(crew, section)
        leader_row = BasketShifter.objects.filter(
            basket=basket, enddate__isnull=True, shifter__isactive=True,
        ).select_related('shifter__minerlevel').first() if basket else None
        leader = leader_row.shifter if leader_row else None
        pending_row = None if leader else BasketShifter.objects.filter(
            basket=basket, enddate__isnull=True, shifter__onboarding_status='pending',
        ).select_related('shifter').first() if basket else None
        pending_leader = pending_row.shifter if pending_row else None
        members = active.filter(basket=basket).values('employee_id').distinct().count() if basket else 0
        sections.append({'section': section, 'leader': leader, 'pending_leader': pending_leader, 'members': members})

    return render(request, 'users/crew_management_crew.html', {'crew': crew, 'sections': sections})


def _full_name(person):
    return f'{person.firstname} {person.lastname}' if person else ''


def _recent_seats(person, limit=5):
    # The newest seat rows for one person, for the basket's History panel.
    rows = CrewAssignment.objects.filter(employee=person).select_related('basket__crew', 'basket__group', 'basket__discipline', 'positionid').order_by('-startdate')[:limit]
    return [
        {
            'where': _basket_label(a.basket) + (f" · {a.positionid.positionname}" if a.positionid else ''),
            'start': a.startdate.strftime('%b %d, %Y') if a.startdate else '',
            'end': a.enddate.strftime('%b %d, %Y') if a.enddate else 'current',
        }
        for a in rows
    ]


def _recent_covers(person, limit=5):
    # The newest coverage rows where this person covered or was covered, for the History panel.
    rows = CrewCoverage.objects.filter(Q(covering_shifter=person) | Q(home_shifter=person)).select_related('basket__crew', 'basket__group', 'basket__discipline', 'covering_shifter', 'home_shifter').order_by('-startdate')[:limit]
    return [
        {
            'where': _basket_label(c.basket),
            'role': 'Covering' if c.covering_shifter_id == person.pk else 'Covered',
            'with': _full_name(c.home_shifter if c.covering_shifter_id == person.pk else c.covering_shifter),
            'start': c.startdate.strftime('%b %d, %Y') if c.startdate else '',
            'end': c.enddate.strftime('%b %d, %Y') if c.enddate else 'current',
        }
        for c in rows
    ]


def _recent_level_changes(person, limit=5, scan=50):
    # The newest Level/Contract changes for one person, for the History panel.
    # Auditlog.employeeid is the actor who made the change, not this person —
    # the only way to find rows about them is tablename='Employee' + their
    # own eid as recordid, same lookup last_rejection_note uses elsewhere.
    # Scans the last `scan` log rows for this employee (any action) rather
    # than filtering by action name, so it also catches a level change made
    # as a side effect of something else (a promotion, demotion, or rehire),
    # not just the dedicated Edit Level/Contract action.
    rows = Auditlog.objects.filter(
        tablename='Employee', recordid=person.eid,
    ).order_by('-timestamp')[:scan]
    changes = []
    for row in rows:
        if not row.newvalue or 'minerlevel' not in row.newvalue:
            continue
        changes.append({
            'action': row.action,
            'from': (row.oldvalue or {}).get('minerlevel') or '—',
            'to': row.newvalue.get('minerlevel') or '—',
            'at': row.timestamp.strftime('%b %d, %Y'),
        })
        if len(changes) >= limit:
            break
    return changes


@login_required(login_url='login')
def crew_management_basket(request, crewname, section):
    # One basket: the shifter on top, then the members, with the basket actions.
    if request.user.access_level not in (1, 2):
        return redirect('profile')
    if section not in management_sections().get(crewname, []):
        raise Http404
    crew = get_object_or_404(Crews, crewname=crewname, isactive=1)

    basket = basket_for(crew, section)
    seats = CrewAssignment.objects.filter(basket=basket) if basket else CrewAssignment.objects.none()
    leader_row = BasketShifter.objects.filter(
        basket=basket, enddate__isnull=True, shifter__isactive=True,
    ).select_related('shifter__minerlevel', 'shifter__contractid', 'shifter__roleid').first() if basket else None
    leader = leader_row.shifter if leader_row else None

    covering_ids = set(CrewCoverage.objects.filter(enddate__isnull=True).values_list('covering_shifter_id', flat=True))
    covering_here = CrewCoverage.objects.filter(
        enddate__isnull=True, basket=basket,
    ).select_related('covering_shifter').first() if basket else None
    # A hire waiting on IT access holds the basket's leader seat until IT activates them.
    pending_row = BasketShifter.objects.filter(
        basket=basket, enddate__isnull=True, shifter__onboarding_status='pending',
    ).select_related('shifter__minerlevel').first() if basket else None
    pending_leader = pending_row.shifter if pending_row else None

    members = []
    member_histories = {}
    for a in seats.filter(
        enddate__isnull=True, employee__isnull=False,
    ).select_related('employee__roleid', 'employee__minerlevel', 'employee__contractid', 'positionid').order_by('employee__lastname', 'employee__firstname'):
        members.append({
            'assignment': a, 'employee': a.employee, 'covering': a.employee_id in covering_ids,
            'also': _basket_label(a.also_covers_basket) if a.also_covers_basket_id else None,
        })
        member_histories[a.employee.employeeid] = {
            'name': f'{a.employee.firstname} {a.employee.lastname}',
            'seats': _recent_seats(a.employee),
            'covers': _recent_covers(a.employee),
            'levels': _recent_level_changes(a.employee),
        }

    # People whose home is another crew but who also cover this one.
    also_here = []
    if basket:
        for a in CrewAssignment.objects.filter(also_covers_basket=basket, enddate__isnull=True).select_related('employee', 'basket__crew', 'basket__group', 'basket__discipline'):
            also_here.append({'employee': a.employee, 'home': _basket_label(a.basket)})

    # Quit or moved out: the last 10 roster rows that ended in this basket.
    # "Quit" means THIS row ended the day they quit outright (_retire_shifter
    # sets terminationdate to the same date it ends their seat) — not just
    # "they're inactive today", which would relabel every older remove/replace/
    # promotion row as a Quit too, the moment they later quit for any reason.
    ended = []
    for a in seats.filter(
        enddate__isnull=False, employee__isnull=False,
    ).select_related('employee').order_by('-enddate')[:10]:
        ended.append({'employee': a.employee, 'enddate': a.enddate, 'quit': a.enddate == a.employee.terminationdate})

    return render(request, 'users/crew_management_basket.html', {
        **grid_action_data(),
        'crew': crew,
        'section': section,
        'basket_key': f'{crew.crewid}:{section}',
        'leader': leader,
        'pending_leader': pending_leader,
        'pending_leader_count': User.objects.filter(onboarding_status='pending', roleid__accessid__accessid=5).count(),
        'covering_here': covering_here,
        'members': members,
        'home_label': f'Crew {crew.crewname} — {section}',
        'basket_value': f'{crew.crewid}:{section}',
        'move_url': reverse('crew_assignment_detail', args=[leader.employeeid]) if leader else reverse('crew_assignments'),
        'move_positions': Position.objects.filter(isactive=1, discipline_id=basket.discipline_id).order_by('sortorder', 'positionname') if basket else [],
        'also_here': also_here,
        'ended': ended,
        'minerlevel_choices': _miner_level_choices(),
        'member_histories': member_histories,
    })


def _active_basket_row(active_basket):
    # The basket row for a (crew, discipline) pair picked on the per-seat page.
    return basket_for(active_basket[0], active_basket[1]) if active_basket else None


@login_required(login_url='login')
def crew_assignment_detail(request, shifter_id):
    if request.user.access_level not in (1, 2):
        return redirect('profile')

    shifter = get_object_or_404(User, employeeid=shifter_id, roleid__accessid__accessid=5, isactive=True)

    active_assignments = CrewAssignment.objects.filter(
        shifter=shifter,
        enddate__isnull=True
    ).select_related('employee', 'positionid', 'crewid')

    basket_list = shifter.get_active_baskets()

    # Which basket the Add Members form is scoped to right now. With only one
    # basket this is automatic and invisible; with more than one, a picker
    # (GET-based, so choosing is a plain navigation, not a data change) decides.
    active_basket = None
    if len(basket_list) == 1:
        active_basket = basket_list[0]
    elif len(basket_list) > 1:
        chosen = request.GET.get('basket') or request.POST.get('basket')
        if chosen and ':' in chosen:
            chosen_crewid, chosen_shiftertype = chosen.split(':', 1)
            active_basket = next(
                (b for b in basket_list if str(b[0].crewid) == chosen_crewid and b[1] == chosen_shiftertype),
                None,
            )

    assigned_ids = CrewAssignment.objects.filter(enddate__isnull=True).values_list('employee_id', flat=True)
    # Miners, plus Spare Shifters currently covering another basket — covering
    # is a leadership role on a different crew (CrewCoverage), not a member
    # seat, so it doesn't stop someone also being added as a plain member
    # here. Only an existing member seat (CrewAssignment) does that.
    available_employees = User.objects.filter(
        Q(roleid__accessid__accessid=8) | Q(roleid__rolename='Spare Shifter'), isactive=True,
    ).exclude(eid__in=assigned_ids)

    # Every active Miner, for the Replace panel — includes people currently
    # assigned elsewhere (picking one moves them: their old assignment ends
    # automatically), labeled with where they currently are so it's clear
    # which selections are a plain fill vs. a move.
    all_miners = list(User.objects.filter(roleid__accessid__accessid=8, isactive=True).order_by('lastname', 'firstname'))
    active_by_employee = {
        a.employee_id: a for a in CrewAssignment.objects.filter(enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline')
    }
    for m in all_miners:
        current = active_by_employee.get(m.eid)
        m.current_assignment_label = _basket_label(current.basket) if current else None

    # Other active shifters, for Transfer Basket's "who receives it" picker.
    other_shifters = User.objects.filter(
        roleid__accessid__accessid=5, isactive=True
    ).exclude(eid=shifter.eid).order_by('lastname', 'firstname')

    # Unclassified positions stay visible as a fallback while the Superintendent
    # is still gradually classifying the catalog (Position Catalog page).
    positions = Position.objects.filter(isactive=1)
    if active_basket:
        positions = positions.filter(Q(discipline__name=active_basket[1]) | Q(discipline__isnull=True))

    active_row = _active_basket_row(active_basket)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'bulk_add_members':
            start_date = request.POST.get('startdate')
            employee_ids = request.POST.getlist('employee_ids')
            added = []
            for employee_id in employee_ids:
                # Matches available_employees above: a Miner, or a Spare
                # Shifter currently covering a different basket — covering is
                # a leadership role elsewhere, not a member seat here.
                employee = get_object_or_404(
                    User, Q(roleid__accessid__accessid=8) | Q(roleid__rolename='Spare Shifter'),
                    employeeid=employee_id, isactive=True,
                )
                position_id = request.POST.get(f'position_{employee_id}') or None
                also, also_error = _also_covers_basket(request, employee_id, active_row)
                if also_error:
                    messages.error(request, also_error)
                    break
                CrewAssignment.objects.create(
                    shifter=shifter,
                    employee=employee,
                    positionid_id=position_id,
                    startdate=start_date,
                    crewid=active_basket[0] if active_basket else None,
                    shiftertype=active_basket[1] if active_basket else None,
                    also_covers_basket=also,
                )
                added.append(f'{employee.firstname} {employee.lastname}')
            if added:
                messages.success(request, f'Added {len(added)} member{"s" if len(added) != 1 else ""} to crew: {", ".join(added)}.')
            else:
                messages.warning(request, 'No members selected.')

        elif action == 'bulk_remove_members':
            assignment_ids = request.POST.getlist('assignment_ids')
            qs = CrewAssignment.objects.filter(assignmentid__in=assignment_ids, shifter=shifter, enddate__isnull=True)
            count = qs.count()
            if count:
                qs.update(enddate=timezone.now().date(), active_employee_key=None)
                messages.success(request, f'Removed {count} member{"s" if count != 1 else ""} from crew.')
            else:
                messages.warning(request, 'No members selected.')

        elif action == 'replace_position':
            old_assignment = get_object_or_404(
                CrewAssignment, assignmentid=request.POST.get('assignment_id'), shifter=shifter, enddate__isnull=True
            )
            existing_employeeid = request.POST.get('existing_employeeid', '').strip()

            replacement = None
            moved_from_elsewhere = False
            new_hire_pending = False
            if existing_employeeid:
                replacement = get_object_or_404(
                    User, employeeid=existing_employeeid, roleid__accessid__accessid=8, isactive=True
                )
                if replacement.eid == old_assignment.employee_id:
                    messages.warning(request, f'{replacement.firstname} {replacement.lastname} is already in that position.')
                    replacement = None
                else:
                    # Moving them: any active assignment elsewhere ends automatically —
                    # a Miner only ever holds one position at a time.
                    other_active = CrewAssignment.objects.filter(employee=replacement, enddate__isnull=True)
                    moved_from_elsewhere = other_active.exists()
                    other_active.update(enddate=timezone.now().date(), active_employee_key=None)
            else:
                new_employeeid = request.POST.get('new_employeeid', '').strip()
                new_firstname = request.POST.get('new_firstname', '').strip()
                new_lastname = request.POST.get('new_lastname', '').strip()
                new_phone = request.POST.get('new_phonenumber', '').strip()

                if User.objects.filter(employeeid=new_employeeid).exists():
                    messages.error(request, f"Employee ID '{new_employeeid}' already exists.")
                elif not all([new_employeeid, new_firstname, new_lastname, new_phone]):
                    messages.error(request, "All fields are required to hire a new replacement.")
                else:
                    miner_role = get_object_or_404(Roles, rolename='Underground Mine Operator')
                    replacement = User(
                        employeeid=new_employeeid,
                        firstname=new_firstname,
                        lastname=new_lastname,
                        phonenumber=new_phone,
                        roleid=miner_role,
                        isactive=False,
                        hasaccess=True,
                        is_temporary=True,
                        employmenttype='Contract',
                        onboarding_status='pending',
                        onboarding_requested_by=request.user,
                        onboarding_requested_on=timezone.now().date(),
                    )
                    replacement.set_unusable_password()
                    replacement.save()
                    new_hire_pending = True

            if replacement:
                today = timezone.now().date()
                old_assignment.enddate = today
                old_assignment.save(update_fields=['enddate'])

                also, also_error = _also_covers_from_value(request.POST.get('also_covers', ''), old_assignment.basket)
                if also_error:
                    messages.error(request, also_error)
                    also = None
                CrewAssignment.objects.create(
                    shifter=shifter,
                    employee=replacement,
                    positionid=old_assignment.positionid,
                    startdate=today,
                    crewid=old_assignment.crewid,
                    shiftertype=old_assignment.shiftertype,
                    also_covers_basket=also,
                )
                position_label = old_assignment.positionid.positionname if old_assignment.positionid else 'the crew'
                if new_hire_pending:
                    messages.success(request, f"{replacement.firstname} {replacement.lastname} added to {position_label} as a pending hire. They can't log in until IT activates their access.")
                elif moved_from_elsewhere:
                    messages.success(request, f'{replacement.firstname} {replacement.lastname} moved to {position_label} (their previous assignment was ended).')
                else:
                    messages.success(request, f'{replacement.firstname} {replacement.lastname} assigned to {position_label}.')

        elif action == 'transfer_basket':
            new_shifter_id = request.POST.get('new_shifter_id', '').strip()
            promote_employee_id = request.POST.get('promote_employee_id', '').strip()
            new_shifter = None
            if not active_basket:
                messages.error(request, 'Select a basket to transfer first.')
            elif not new_shifter_id and not promote_employee_id:
                messages.error(request, 'Select a shifter to transfer this basket to.')
            elif promote_employee_id:
                # Transfer's destination can be a permanent promotion straight
                # from the Miner ranks — a one-way handoff, so only the
                # permanent role fits here; a temporary Spare Shifter fill
                # belongs to Start Coverage instead, which keeps this shifter
                # as the basket's nominal owner rather than ending their hold.
                miner = get_object_or_404(User, employeeid=promote_employee_id, roleid__accessid__accessid=8, isactive=True)
                shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
                old_role_values = {'roleid': miner.roleid_id, 'minerlevel': _level_code(miner.minerlevel)}
                miner.roleid = shifter_role
                _leave_member_seats(miner)
                miner.minerlevel = _staff_level()
                miner.save(update_fields=['roleid', 'minerlevel'])
                log_action(request.user, 'Promote to Shifter (Permanent)', 'Employee', miner.eid,
                           old_role_values, {'roleid': shifter_role.roleid, 'minerlevel': 'Staff'})
                new_shifter = miner
            else:
                new_shifter = get_object_or_404(User, employeeid=new_shifter_id, roleid__accessid__accessid=5, isactive=True)
                if new_shifter.eid == shifter.eid:
                    messages.error(request, 'Pick a different shifter to transfer to.')
                    new_shifter = None

            if new_shifter:
                rows = CrewAssignment.objects.filter(
                    shifter=shifter, basket=active_row, enddate__isnull=True
                )
                members = list(rows)
                today = timezone.now().date()

                old_values = {'shifter': shifter.eid, 'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1]}
                rows.update(enddate=today, active_employee_key=None)
                CrewAssignment.objects.bulk_create([
                    CrewAssignment(
                        shifter=new_shifter, employee=m.employee, positionid=m.positionid,
                        startdate=today, crewid=active_basket[0], shiftertype=active_basket[1],
                        # Transfer only changes who runs the basket, so each member's
                        # also-covers crew carries over unchanged.
                        also_covers_basket=m.also_covers_basket,
                    ) for m in members
                ])

                # If this was the departing shifter's own home basket, clear it —
                # they no longer run it. A shifter transferring away a second
                # (non-home) basket keeps their home identity untouched.
                if active_row is not None and _home_basket(shifter) == active_row:
                    shifter.crewid = None
                    shifter.shiftertype = None
                    shifter.save(update_fields=['crewid', 'shiftertype', 'discipline'])

                BasketLead.objects.filter(
                    shifter=shifter, basket=active_row, enddate__isnull=True
                ).update(enddate=today)
                becomes_coverage = bool(_home_basket(new_shifter))
                _hand_over_basket(new_shifter, active_basket[0], active_basket[1], today, request.user)

                log_action(request.user, 'Transfer Basket', 'CrewAssignment', shifter.eid,
                           old_values, {'shifter': new_shifter.eid, 'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1]})
                verb = 'to cover' if becomes_coverage else 'to'
                messages.success(
                    request,
                    f'Transferred Crew {active_basket[0].crewname} — {active_basket[1]} '
                    f'({len(members)} member{"s" if len(members) != 1 else ""}) {verb} {new_shifter.firstname} {new_shifter.lastname}.'
                )
                next_url = request.POST.get('next', '').strip()
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect(reverse('crew_grid'))

        elif action == 'start_coverage':
            # Reversible sibling of transfer_basket: moves the same roster
            # rows in place (never ends/recreates them) and never touches
            # this shifter's own home crewid/shiftertype — they stay the
            # basket's nominal owner and the rows come straight back to them
            # when the coverage ends (Crew Coverage's own "end" action).
            covering_shifter_id = request.POST.get('covering_shifter_id', '').strip()
            promote_employee_id = request.POST.get('promote_employee_id', '').strip()
            startdate = request.POST.get('startdate') or timezone.now().date()
            if not isinstance(startdate, date_type):
                startdate = date_type.fromisoformat(startdate)
            notes = request.POST.get('notes') or None
            covering = None
            if not active_basket:
                messages.error(request, 'Select a basket to cover first.')
            elif not covering_shifter_id and not promote_employee_id:
                messages.error(request, 'Select who is covering this basket.')
            elif promote_employee_id:
                # Only a temporary (Spare Shifter) promotion fits Coverage —
                # a permanent one belongs to Transfer, which actually ends
                # this shifter's hold on the basket instead of handing it
                # back later. Same Lead/1/2 floor as every other Spare
                # Shifter promotion in the app.
                miner = get_object_or_404(
                    User, employeeid=promote_employee_id, roleid__accessid__accessid=8,
                    minerlevel__levelcode__in=['Lead', '1', '2'], isactive=True,
                )
                spare_role = get_object_or_404(Roles, rolename='Spare Shifter')
                old_role_values = {'roleid': miner.roleid_id}
                miner.roleid = spare_role
                miner.save(update_fields=['roleid'])
                log_action(request.user, 'Promote to Spare Shifter', 'Employee', miner.eid,
                           old_role_values, {'roleid': spare_role.roleid})
                covering = miner
            else:
                covering = get_object_or_404(User, employeeid=covering_shifter_id, roleid__accessid__accessid=5, isactive=True)
                if covering.eid == shifter.eid:
                    messages.error(request, 'Pick a different shifter to cover this basket.')
                    covering = None

            if covering and _coverage_overlaps(active_basket[0], active_basket[1], startdate):
                messages.error(request, f'Crew {active_basket[0].crewname} — {active_basket[1]} already has a coverage that runs past {startdate:%b %d, %Y}.')
                covering = None
            if covering:
                moved = CrewAssignment.objects.filter(
                    shifter=shifter, basket=active_row, enddate__isnull=True
                ).update(shifter=covering)
                CrewCoverage.objects.create(
                    covering_shifter=covering, home_shifter=shifter,
                    crewid=active_basket[0], shiftertype=active_basket[1],
                    startdate=startdate, notes=notes, assignedby=request.user,
                )
                log_action(request.user, 'Start Coverage', 'CrewAssignment', shifter.eid,
                           {'shifter': shifter.eid}, {'shifter': covering.eid, 'covering_for': shifter.eid})
                messages.success(
                    request,
                    f'{covering.firstname} {covering.lastname} is now covering Crew {active_basket[0].crewname} — {active_basket[1]} '
                    f'for {shifter.firstname} {shifter.lastname} ({moved} member{"s" if moved != 1 else ""} moved).'
                )
                next_url = request.POST.get('next', '').strip()
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect(reverse('crew_grid'))

        elif action == 'move_position':
            # Drag-and-drop from the Crew Grid: relocate one person from their
            # current assignment to a slot elsewhere — same "move" as
            # replace_position's existing-employee path (end the old row,
            # start a new one), just without a destination assignment to end
            # since the grid only ever offers an empty slot as a drop target.
            # A position can legitimately hold more than one person (e.g. 4
            # Water Management on one basket), so landing on a position that
            # already has occupants elsewhere in its lane is expected, not
            # blocked — the lane just grows by one row on next render.
            if not active_basket:
                messages.error(request, 'Select a basket to move a member into first.')
            else:
                source = get_object_or_404(
                    CrewAssignment, assignmentid=request.POST.get('source_assignment_id'), enddate__isnull=True
                )
                dest_position_id = request.POST.get('dest_position_id') or None
                dest_position_id = int(dest_position_id) if dest_position_id else None
                if source.basket_id == getattr(active_row, 'pk', None) and source.positionid_id == dest_position_id:
                    messages.warning(request, f'{source.employee.firstname} {source.employee.lastname} is already there.')
                else:
                    today = timezone.now().date()
                    old_values = {'crewid': source.crewid_id, 'shiftertype': source.shiftertype, 'positionid': source.positionid_id}
                    source.enddate = today
                    source.save(update_fields=['enddate'])
                    CrewAssignment.objects.create(
                        shifter=shifter, employee=source.employee, positionid_id=dest_position_id,
                        startdate=today, crewid=active_basket[0], shiftertype=active_basket[1],
                        also_covers_basket=_carried_also_covers(source, active_row),
                    )
                    log_action(request.user, 'Move Crew Member', 'CrewAssignment', source.employee_id, old_values,
                               {'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1], 'positionid': dest_position_id})
                    messages.success(request, f'Moved {source.employee.firstname} {source.employee.lastname}.')

        redirect_url = reverse('crew_grid')
        if len(basket_list) > 1 and active_basket:
            redirect_url += f'?basket={active_basket[0].crewid}:{active_basket[1]}'
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(redirect_url)

    return redirect('crew_management')



# Discipline bands in the order they appear on the Superintendent's paper/Excel
# sheet, and which Crews columns each band draws from. Development/Production
# are run per single crew (A/B/C/D); Longhole/Logistics are jointly staffed by
# the AB/CD crews, which are already their own real Crews rows (no new schema
# needed — they just render merged across the A/B and C/D columns visually).
def grid_layout():
    """The Crew Grid's shape, read from the database rather than fixed lists.
    Each discipline with at least one unit is a row band, and each unit that runs
    it is a column. A joint crew (a group such as AB) spans the single-crew columns
    it's made of. Single crews sit in name order (A, B, C, ...)."""
    singles = single_crews()
    column_of = {c.crewname: i for i, c in enumerate(singles)}
    crew_by_name = {c.crewname: c for c in Crews.objects.filter(isactive=1)}

    units_by_discipline = {}
    for link in UnitDiscipline.objects.select_related('crew', 'group', 'discipline').filter(discipline__isactive=1):
        if link.crew_id:
            if not link.crew.isactive:
                continue
            unit = {'crew': link.crew, 'basket': link, 'colspan': 1, 'is_group': False,
                    'order': column_of.get(link.crew.crewname, len(column_of))}
        else:
            members = sorted(
                (m.crew for m in link.group.members.select_related('crew')),
                key=lambda c: column_of.get(c.crewname, len(column_of)),
            )
            crew = crew_by_name.get(link.group.groupname)
            if crew is None or not members:
                continue
            unit = {'crew': crew, 'basket': link, 'colspan': len(members), 'is_group': True,
                    'order': column_of.get(members[0].crewname, len(column_of))}
        units_by_discipline.setdefault(link.discipline, []).append(unit)

    bands = []
    for discipline in Discipline.objects.filter(isactive=1).order_by('sortorder', 'name'):
        units = sorted(units_by_discipline.get(discipline, []), key=lambda u: u['order'])
        if units:
            bands.append({'label': discipline.name, 'discipline': discipline, 'units': units})

    # Two-crew groups (AB, CD, ...) joined by name-free membership. pair_map feeds
    # the "Also covers" option on Add/Replace.
    pairs = {}
    pair_map = {}
    for group in CrewGroup.objects.filter(isactive=1):
        members = [m.crew for m in group.members.select_related('crew')]
        joint = crew_by_name.get(group.groupname)
        if len(members) != 2 or joint is None or any(len(m.crewname) != 1 for m in members):
            continue
        a, b = members
        pairs[frozenset((a.crewid, b.crewid))] = joint
        pair_map[str(a.crewid)] = {'partner_name': b.crewname, 'joint_crewid': joint.crewid}
        pair_map[str(b.crewid)] = {'partner_name': a.crewname, 'joint_crewid': joint.crewid}

    positions = {}
    for p in Position.objects.filter(isactive=1, discipline__isnull=False).select_related('discipline').order_by('sortorder', 'positionname'):
        positions.setdefault(p.discipline.name, []).append(p)

    return {
        'singles': [c.crewname for c in singles],
        'bands': bands,
        'pairs': pairs,
        'pair_map': pair_map,
        'positions': positions,
    }


def _move_targets():
    # Every basket a person can be moved into, with the discipline its positions must match.
    targets = []
    for basket in UnitDiscipline.objects.select_related('crew', 'group', 'discipline').order_by('discipline__sortorder', 'pk'):
        crew = basket.crew_row
        if crew is None:
            continue
        targets.append({'value': f'{crew.crewid}:{basket.discipline.name}', 'label': _basket_label(basket), 'discipline': basket.discipline.name})
    return targets


def _move_positions_by_discipline():
    positions = {}
    for p in Position.objects.filter(isactive=1, discipline__isnull=False).select_related('discipline').order_by('sortorder', 'positionname'):
        positions.setdefault(p.discipline.name, []).append({'id': p.positionid, 'name': p.positionname})
    return positions


def _also_covers_options():
    """For each single-crew basket, the other single-crew baskets for the same discipline.
    Read from the unit links, so a crew only appears when it runs that discipline."""
    singles = [b for b in UnitDiscipline.objects.select_related('crew', 'discipline') if b.crew_id and len(b.crew.crewname) == 1]
    options = {}
    for basket in singles:
        key = f'{basket.crew_id}:{basket.discipline.name}'
        options[key] = [
            {'value': f'{other.crew_id}:{other.discipline.name}', 'label': f'Crew {other.crew.crewname} — {other.discipline.name}'}
            for other in singles
            if other.pk != basket.pk and other.discipline_id == basket.discipline_id
        ]
    return options


@login_required(login_url='login')
def person_move(request):
    # Moves one seat to another position in its basket, or to another basket with a position.
    # Used by the person panel on Crew Management. Any basket can take a seat, led or not.
    if request.user.access_level not in (1, 2) or request.method != 'POST':
        return redirect('crew_management')
    # Crew Grid is read-only by design (its own view says so) — the person
    # panel's move controls are hidden there and drag-and-drop is disabled,
    # but both pages share this one endpoint at the same access level, so a
    # direct POST bypassing the UI would otherwise still go through. Reject
    # it here too, keyed off the same `next` destination the UI itself sends.
    next_url = request.POST.get('next', '').strip()
    try:
        if next_url and resolve(next_url).url_name == 'crew_grid':
            messages.error(request, 'Moves are not available from the Crew Grid — use Crew Management instead.')
            return redirect('crew_grid')
    except Resolver404:
        pass
    source = get_object_or_404(CrewAssignment, assignmentid=request.POST.get('source_assignment_id'), enddate__isnull=True)
    crew, section = _parse_basket(request.POST.get('basket'))
    target = basket_for(crew, section) if crew and section else None
    position = Position.objects.filter(pk=request.POST.get('dest_position_id') or None).select_related('discipline').first()
    if target is None or position is None:
        messages.error(request, 'Choose a basket and a position.')
    elif position.discipline_id != target.discipline_id:
        messages.error(request, f'{position.positionname} belongs to {position.discipline.name if position.discipline else "no discipline"}, so it can\'t go in a {target.discipline.name} basket.')
    elif source.basket_id == target.pk and source.positionid_id == position.pk:
        messages.warning(request, f'{source.employee.firstname} {source.employee.lastname} is already there.')
    else:
        today = timezone.now().date()
        also = source.also_covers_basket if source.also_covers_basket_id and not also_covers_error(target, source.also_covers_basket) else None
        leader_row = BasketShifter.objects.filter(basket=target, enddate__isnull=True, shifter__isactive=True).select_related('shifter').first()
        old_values = {'basket': str(source.basket_id), 'positionid': source.positionid_id}
        with transaction.atomic():
            source.enddate = today
            source.save(update_fields=['enddate'])
            new_seat = CrewAssignment.objects.create(
                shifter=leader_row.shifter if leader_row else None, employee=source.employee,
                positionid=position, startdate=today, crewid=crew, shiftertype=section,
                also_covers_basket=also,
            )
            log_action(request.user, 'Move Crew Member', 'CrewAssignment', source.employee_id, old_values,
                       {'basket': str(new_seat.basket_id), 'positionid': position.positionid})
        messages.success(request, f'Moved {source.employee.firstname} {source.employee.lastname} to {_basket_label(target)} — {position.positionname}.')
    next_url = request.POST.get('next', '').strip()
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('crew_management')


def _carried_also_covers(source, new_basket):
    """A moved seat keeps its also-covers crew, if that crew is still valid for the new basket."""
    target = source.also_covers_basket
    if target is None or new_basket is None or also_covers_error(new_basket, target):
        return None
    return target


def _also_covers_from_value(value, primary):
    """The also-covers basket for a picked value ('crewid:Discipline'), or None. Returns (basket, error)."""
    if not value:
        return None, None
    crew, section = _parse_basket(value)
    target = basket_for(crew, section) if crew and section else None
    if target is None:
        return None, 'That also-covers crew doesn\'t run this discipline.'
    error = also_covers_error(primary, target)
    return (None, error) if error else (target, None)


def _also_covers_basket(request, employee_id, primary):
    return _also_covers_from_value(request.POST.get(f'also_covers_{employee_id}', ''), primary)


def grid_action_data():
    # Everything the Crew Grid's action modals read. Shared with the basket page, so both pages open the same modals on the same data.
    layout = grid_layout()
    active_assignments = list(
        CrewAssignment.objects.filter(enddate__isnull=True)
        .select_related('employee', 'positionid', 'crewid', 'shifter', 'basket__crew', 'basket__group', 'basket__discipline')
    )

    # Data for the inline Add/Replace/Transfer modals — plain JSON-able lists,
    # rendered via json_script and read by the grid's JS, which populates and
    # points a single shared modal per action type at whichever basket/cell
    # was clicked rather than pre-rendering one form per cell.
    unclassified_positions = list(
        Position.objects.filter(isactive=1, discipline__isnull=True).order_by('positionname').values('positionid', 'positionname')
    )
    positions_for_modal = {}
    for label in [band['label'] for band in layout['bands']]:
        items = [{'id': p.positionid, 'name': p.positionname} for p in layout['positions'].get(label, [])]
        items += [{'id': p['positionid'], 'name': p['positionname']} for p in unclassified_positions]
        positions_for_modal[label] = items

    # For the "Also covers Crew ___" hook on Add/Replace — which joint AB/CD
    # crew each single crew belongs to, and its pair partner's name, so the
    # form can offer the option only where it makes sense (adding to a plain
    # A/B/C/D column, never to an already-joint AB/CD one) without needing a
    # new pairing concept beyond the two that already exist.
    crew_pair_map = layout['pair_map']

    assigned_ids = CrewAssignment.objects.filter(enddate__isnull=True).values_list('employee_id', flat=True)
    # Miners, plus Spare Shifters currently covering another basket (see the
    # same note on crew_assignment_detail's available_employees above).
    available_employees = User.objects.filter(
        Q(roleid__accessid__accessid=8) | Q(roleid__rolename='Spare Shifter'), isactive=True,
    ).exclude(eid__in=assigned_ids).order_by('lastname', 'firstname')
    available_employees_for_modal = [
        {'employeeid': e.employeeid, 'name': f'{e.firstname} {e.lastname}'} for e in available_employees
    ]

    active_by_employee = {}
    for a in active_assignments:
        active_by_employee.setdefault(a.employee_id, a)
    all_miners_for_modal = []
    for m in User.objects.filter(roleid__accessid__accessid=8, isactive=True).order_by('lastname', 'firstname'):
        current = active_by_employee.get(m.eid)
        current_label = _basket_label(current.basket) if current and current.basket_id else None
        # minerlevel travels along so the JS can filter to Lead/1/2 for the
        # Spare Shifter (temporary) picker without a second near-duplicate
        # server-side list — the permanent-promotion pickers use the full set.
        all_miners_for_modal.append({
            'employeeid': m.employeeid, 'name': f'{m.firstname} {m.lastname}',
            'current_label': current_label, 'minerlevel': _level_code(m.minerlevel),
        })

    busy_cover_ids = set()
    for cov in CrewCoverage.objects.filter(enddate__isnull=True):
        busy_cover_ids.add(cov.covering_shifter_id)
        if cov.home_shifter_id:
            busy_cover_ids.add(cov.home_shifter_id)
    home_by_shifter = {
        row.shifter_id: row.basket
        for row in BasketShifter.objects.filter(is_home=True, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline')
    }
    all_shifters_for_modal = [
        {
            'employeeid': s.employeeid, 'name': f'{s.firstname} {s.lastname}',
            'current_label': _basket_label(home_by_shifter[s.pk]) if s.pk in home_by_shifter else None,
            'busy_cover': s.pk in busy_cover_ids,
        }
        for s in User.objects.filter(roleid__accessid__accessid=5, isactive=True).order_by('lastname', 'firstname')
    ]

    # Contract Code choices for the Edit Level/Contract modal, keyed by Level id.
    # A contract with no Level is unclassified and stays hidden until it is
    # given one (classified on the Contract mapping page).
    contracts_for_modal = contracts_by_miner_level()

    panel_people = User.objects.filter(
        Q(roleid__accessid__accessid__in=[5, 8]) | Q(onboarding_status='pending') | Q(isactive=False, terminationdate__isnull=False)
    ).select_related('roleid', 'contractid', 'crewid').distinct()
    person_panels = {}
    for u in panel_people:
        seats = list(CrewAssignment.objects.filter(employee=u, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline', 'positionid'))
        covers = list(CrewCoverage.objects.filter(covering_shifter=u, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline'))
        leads = u.get_active_baskets() if u.access_level == 5 else []
        def basket_label(crew, st):
            return f"Crew {crew.crewname if crew else '?'} — {st or '?'}"
        def seat_label(obj):
            return _basket_label(obj.basket)
        if not u.isactive and u.terminationdate:
            status = f"Quit {u.terminationdate:%b %d, %Y}"
        elif u.onboarding_status == 'pending':
            status = 'Pending IT access'
        elif covers:
            status = 'Covering ' + ', '.join(seat_label(c) for c in covers)
        elif leads:
            status = 'Leads ' + ', '.join(basket_label(c, st) for c, st in leads)
        elif seats:
            status = 'Seated in ' + ', '.join(seat_label(a) for a in seats)
        else:
            status = 'Unassigned'
        history = [
            {
                'seat': f"{seat_label(a)}" + (f" — {a.positionid.positionname}" if a.positionid else ''),
                'start': a.startdate.isoformat() if a.startdate else '',
                'end': a.enddate.isoformat() if a.enddate else 'current',
            }
            for a in CrewAssignment.objects.filter(employee=u).select_related('basket__crew', 'basket__group', 'basket__discipline', 'positionid').order_by('-startdate')[:5]
        ]
        cover_history = [
            {
                'basket': seat_label(c),
                'covering': f"{c.covering_shifter.firstname} {c.covering_shifter.lastname}",
                'home': f"{c.home_shifter.firstname} {c.home_shifter.lastname}" if c.home_shifter else 'vacant basket',
                'start': c.startdate.isoformat(),
                'end': c.enddate.isoformat() if c.enddate else 'current',
            }
            for c in CrewCoverage.objects.filter(Q(covering_shifter=u) | Q(home_shifter=u)).select_related('basket__crew', 'basket__group', 'basket__discipline', 'covering_shifter', 'home_shifter').order_by('-startdate')[:5]
        ]
        level_history = _recent_level_changes(u)
        person_panels[u.employeeid] = {
            'name': f'{u.firstname} {u.lastname}',
            'employeeid': u.employeeid,
            'role': u.roleid.rolename,
            'is_shifter': u.access_level == 5,
            'quit': (not u.isactive) and bool(u.terminationdate),
            'status': status,
            'level': _level_code(u.minerlevel) or '—',
            'contract': u.contractid.contractcode if u.contractid else '—',
            'employment': u.employmenttype or '—',
            'seats': [seat_label(a) + (f" — {a.positionid.positionname}" if a.positionid else '') for a in seats],
            'seat_rows': [
                {'id': a.assignmentid, 'label': seat_label(a), 'position_id': a.positionid_id or '',
                 'basket': f"{a.basket.crew_row.crewid}:{a.basket.discipline.name}" if a.basket.crew_row else ''}
                for a in seats if a.basket_id
            ],
            'minerlevel_id': u.minerlevel_id or '',
            'contractid': u.contractid_id or '',
            'history': history,
            'cover_history': cover_history,
            'level_history': level_history,
        }

    return {
        'positions_for_modal': positions_for_modal,
        'crew_pair_map': crew_pair_map,
        'also_covers_options': _also_covers_options(),
        'move_targets': _move_targets(),
        'move_positions_by_discipline': _move_positions_by_discipline(),
        'available_employees_for_modal': available_employees_for_modal,
        'all_miners_for_modal': all_miners_for_modal,
        'all_shifters_for_modal': all_shifters_for_modal,
        'contracts_for_modal': contracts_for_modal,
        'person_panels': person_panels,
    }


@login_required(login_url='login')
def crew_grid(request):
    """Read-only picture of Crew Management. Each person sits in their primary basket's
    cell for their position, and an also-covers link draws a bracket between the two
    cells on the row. The only actions here are adding a member and adding a position row."""
    if request.user.access_level not in (1, 2):
        return redirect('profile')

    layout = grid_layout()
    active_assignments = list(
        CrewAssignment.objects.filter(enddate__isnull=True)
        .select_related('employee', 'positionid', 'shifter',
                        'basket__crew', 'basket__group', 'basket__discipline',
                        'also_covers_basket__crew', 'also_covers_basket__group', 'also_covers_basket__discipline')
    )
    cell_map = {}
    for a in active_assignments:
        if a.basket_id:
            cell_map.setdefault((a.basket_id, a.positionid_id), []).append(a)

    # Who runs each basket: an active shifter, a covering shifter, or a seat's own shifter.
    leaders = {}
    for row in BasketShifter.objects.filter(enddate__isnull=True, shifter__isactive=True).select_related('shifter'):
        leaders.setdefault(row.basket_id, row.shifter)
    for cov in CrewCoverage.objects.filter(enddate__isnull=True, basket__isnull=False, covering_shifter__isactive=True).select_related('covering_shifter'):
        leaders[cov.basket_id] = cov.covering_shifter
    for a in active_assignments:
        if a.basket_id and a.shifter_id:
            leaders[a.basket_id] = a.shifter
    pending_leader_by_basket = {
        row.basket_id: row.shifter
        for row in BasketShifter.objects.filter(enddate__isnull=True, shifter__onboarding_status='pending').select_related('shifter')
    }
    coverage_by_basket = {
        c.basket_id: c
        for c in CrewCoverage.objects.filter(enddate__isnull=True, basket__isnull=False).select_related('home_shifter', 'covering_shifter')
    }
    basket_has_members = {a.basket_id for a in active_assignments if a.basket_id}

    grid = []
    for band in layout['bands']:
        label = band['label']
        columns = []
        for unit in band['units']:
            basket = unit['basket']
            columns.append({
                'crew': unit['crew'],
                'basket_pk': basket.pk,
                'basket': f"{unit['crew'].crewid}:{label}",
                # A joint crew (AB, CD) spans the two single-crew columns it's made of.
                'colspan': unit['colspan'],
                'shifter': leaders.get(basket.pk),
                'coverage': coverage_by_basket.get(basket.pk),
                'pending_leader': pending_leader_by_basket.get(basket.pk),
                'has_members': basket.pk in basket_has_members,
            })
        basket_pks = {c['basket_pk'] for c in columns}

        position_rows = []
        for position in layout['positions'].get(label, []):
            per_col = [cell_map.get((c['basket_pk'], position.positionid), []) for c in columns]

            # Also-covers links on this row: the covering seat's cell gets "covers X",
            # and the partner's cell gets "also covers Y", so the two can be joined.
            # One partner name per cell (shown once, however many seats link to it).
            links = {}
            for col, occupants in zip(columns, per_col):
                for a in occupants:
                    if a.also_covers_basket_id in basket_pks:
                        links.setdefault(col['basket_pk'], set()).add(a.also_covers_basket.unit_name)
                        links.setdefault(a.also_covers_basket_id, set()).add(a.basket.unit_name)

            lanes = max(
                (-(-len(o) // c['colspan']) for o, c in zip(per_col, columns)),
                default=1,
            ) or 1
            entries = []
            for slot in range(lanes):
                cells = []
                for col, occupants in zip(columns, per_col):
                    size = col['colspan']
                    group = occupants[slot * size:(slot + 1) * size]
                    items = list(group) + [None] * (size - len(group))
                    cells.append({
                        'col': col,
                        'items': items,
                        'links': sorted(links.get(col['basket_pk'], [])),
                    })
                entries.append({'position': position, 'cells': cells})
            # A row is shared when any seat on it covers a partner crew. Seats in a shared row
            # that don't cover one read "<crew> only", so the row says who belongs where.
            row_shared = any(a.also_covers_basket_id for occupants in per_col for a in occupants)
            for idx, entry in enumerate(entries):
                entry['shared'] = row_shared
                entry['is_first'] = idx == 0
                entry['rowspan'] = len(entries)
                position_rows.append(entry)

        grid.append({'label': label, 'columns': columns, 'position_rows': position_rows})

    vacant_baskets = [
        f"Crew {col['crew'].crewname} — {band['label']}"
        for band in grid
        for col in band['columns']
        if not col['shifter'] and not col['coverage'] and not col['pending_leader'] and col['has_members']
    ]
    covering_eids = list(CrewCoverage.objects.filter(enddate__isnull=True).values_list('covering_shifter_id', flat=True))
    return render(request, 'users/crew_grid.html', {
        **grid_action_data(),
        'grid': grid,
        'main_crews': layout['singles'],
        'active_captains': User.objects.filter(roleid__accessid__accessid=4, isactive=True).order_by('lastname', 'firstname'),
        'vacant_baskets': vacant_baskets,
        'covering_eids': covering_eids,
    })

@login_required(login_url='login')
def my_crew(request):
    if request.user.access_level != 5:
        return redirect('profile')

    active_assignments = CrewAssignment.objects.filter(
        shifter=request.user,
        enddate__isnull=True
    ).select_related('employee__roleid')

    return render(request, 'users/my_crew.html', {'active_assignments': active_assignments})


def end_coverage(coverage, today, actor, revert_role=True):
    """Ends a coverage; roster goes back to a live home shifter, else stays vacant."""
    coverage.enddate = today
    coverage.save()

    covering = coverage.covering_shifter
    home = coverage.home_shifter
    handback = home if home and home.isactive and home.access_level == 5 else None

    if coverage.basket_id:
        CrewAssignment.objects.filter(
            shifter=covering, basket_id=coverage.basket_id,
            enddate__isnull=True,
        ).update(shifter=handback)

    warnings = []
    still_covering_elsewhere = CrewCoverage.objects.filter(
        covering_shifter=covering, enddate__isnull=True
    ).exclude(pk=coverage.pk).exists()
    if revert_role and not still_covering_elsewhere and covering.roleid.rolename == 'Spare Shifter':
        if CrewAssignment.objects.filter(shifter=covering, enddate__isnull=True).exists():
            warnings.append(
                f'Coverage ended, but {covering.firstname} {covering.lastname}\'s role was NOT reverted — '
                f'they still run an active basket directly. Transfer it to another shifter first, then '
                f'revert their role via System Admin.'
            )
        else:
            miner_role = get_object_or_404(Roles, rolename='Underground Mine Operator')
            old_values = {'roleid': covering.roleid_id}
            covering.roleid = miner_role
            covering.shiftertype = None
            covering.crewid = None
            covering.save()
            log_action(actor, 'Revert Spare Shifter to Miner', 'Employee', covering.eid,
                       old_values, {'roleid': miner_role.roleid})
    return warnings


@login_required(login_url='login')
def crew_coverage(request):
    # Ending coverage is the only action left on this endpoint. The Crew Grid's End
    # button and the basket's covering card post here. Starting coverage and promoting
    # a Spare Shifter happen on the Crew Grid, so there's no page of its own any more.
    if request.user.access_level not in (2, 4):
        return redirect('profile')

    if request.method == 'POST' and request.POST.get('action') == 'end':
        coverage = get_object_or_404(CrewCoverage, coverageid=request.POST.get('coverage_id'))
        covering_name = f'{coverage.covering_shifter.firstname} {coverage.covering_shifter.lastname}'
        basket_name = _basket_label(coverage.basket)
        for warning in end_coverage(coverage, timezone.now().date(), request.user):
            messages.warning(request, warning)
        messages.success(request, f'Coverage by {covering_name} on {basket_name} ended.')

    next_url = request.POST.get('next', '').strip() if request.method == 'POST' else ''
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('crew_grid')