from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.conf import settings
from users.forms import UserLoginForm
from users.models import User, CrewAssignment, Roles, Position, CrewCoverage, Department
from django.contrib.auth.decorators import login_required
import random
import string
import os
from collections import Counter
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from timesheets.models import MainHeader, MainEntry, OperationsHeader, OperationsEntry, BusinessHeader, BusinessEntry, Crews, Contract, Account, MinerLevel
from django.db.models import Count, Q, Sum
from django.urls import reverse
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

@login_required(login_url='login')
def user_list_view(request):
    if request.user.access_level != 1:
        return redirect('profile')
    users = User.objects.select_related('roleid__departmentid').order_by('roleid__departmentid__departmentname', 'lastname')
    roles = Roles.objects.select_related('departmentid').order_by('departmentid__departmentname', 'rolename')
    active_supervisors = User.objects.filter(isactive=True).select_related('roleid').order_by('lastname', 'firstname')
    crews = Crews.objects.filter(isactive=1)
    contracts = Contract.objects.filter(isactive=1)
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
        'contracts': contracts,
        'accounts': accounts,
        'employment_type_choices': User.EMPLOYMENT_TYPE_CHOICES,
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
        'minerlevel_choices': User.MINER_LEVEL_CHOICES,
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
        shifters = User.objects.filter(supervisorid__in=direct_reports)
        ops_completed_month = OperationsHeader.objects.filter(
            shifterid__in=shifters,
            overallstatus='Completed',
            ohapprovedat_capt__year=today.year,
            ohapprovedat_capt__month=today.month,
        ).count()

        # Workforce headcount — active Shifters (al=5, Spare Shifters included)
        # and active Miners (al=8), mine-wide, not scoped to direct reports.
        total_shifters = User.objects.filter(roleid__accessid__accessid=5, isactive=True).count()
        total_miners = User.objects.filter(roleid__accessid__accessid=8, isactive=True).count()

        return render(request, 'users/profile.html', {
            'today': today,
            'personal_pending': personal_pending,
            'personal_completed': personal_completed,
            'ops_completed_month': ops_completed_month,
            'total_shifters': total_shifters,
            'total_miners': total_miners,
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
        shifters_completed_month = BusinessHeader.objects.filter(
            Q(overallstatus='Completed', completedat__year=today.year, completedat__month=today.month),
            shifter_ownership,
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

        return render(request, 'users/profile.html', {
            'today': today,
            'current_month': today.strftime('%B %Y'),
            'maintenance_pending': maintenance_pending,
            'maintenance_paid_month': maintenance_paid_month,
            'ops_pending': ops_pending,
            'ops_paid_month': ops_paid_month,
            'business_pending': business_pending,
            'business_paid_month': business_paid_month,
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

        if ext in ['jpg', 'jpeg', 'png', 'webp']:
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
        minerlevel   = request.POST.get('minerlevel', '').strip() or None

        if User.objects.filter(employeeid=employeeid).exists():
            messages.error(request, f"Employee ID '{employeeid}' already exists.")
        elif not all([employeeid, firstname, lastname, phonenumber, roleid]):
            messages.error(request, "All required fields must be filled.")
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
        minerlevel = request.POST.get('minerlevel', '').strip() or None

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

        if not all([new_employeeid, firstname, lastname, phonenumber, roleid]):
            messages.error(request, "All required fields must be filled.")
        elif User.objects.exclude(eid=employee.eid).filter(employeeid=new_employeeid).exists():
            messages.error(request, f"Employee ID '{new_employeeid}' is already in use.")
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
                crew_qs.update(enddate=today)
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
def crew_assignments(request):
    if request.user.access_level != 2:
        return redirect('profile')

    shifters = User.objects.filter(
        roleid__accessid__accessid=5,
        isactive=True
    ).annotate(
        crew_count=Count('crew_led', filter=Q(crew_led__enddate__isnull=True))
    ).order_by('lastname', 'firstname')

    miners = User.objects.filter(
        roleid__accessid__accessid=8,
        isactive=True
    ).order_by('lastname', 'firstname')

    if request.method == 'POST' and request.POST.get('action') == 'bulk_update_crews':
        updated = 0
        for shifter in shifters:
            crewid = request.POST.get(f'crewid_{shifter.eid}') or None
            shiftertype = request.POST.get(f'shiftertype_{shifter.eid}') or None
            minerlevel = request.POST.get(f'minerlevel_{shifter.eid}') or None
            employmenttype = request.POST.get(f'employmenttype_{shifter.eid}') or 'Staff'
            changed = (
                shifter.crewid_id != (int(crewid) if crewid else None)
                or shifter.shiftertype != shiftertype
                or shifter.minerlevel != minerlevel
                or shifter.employmenttype != employmenttype
            )
            if changed:
                shifter.crewid_id = crewid
                shifter.shiftertype = shiftertype
                shifter.minerlevel = minerlevel
                shifter.employmenttype = employmenttype
                shifter.save(update_fields=['crewid', 'shiftertype', 'minerlevel', 'employmenttype'])
                updated += 1

        # Miners don't lead a crew/section, but the Superintendent can still reset
        # their seniority level and Staff/Contract classification here — the same
        # two fields a demoted Shifter would carry back down with them.
        for miner in miners:
            minerlevel = request.POST.get(f'minerlevel_{miner.eid}') or None
            employmenttype = request.POST.get(f'employmenttype_{miner.eid}') or 'Staff'
            if miner.minerlevel != minerlevel or miner.employmenttype != employmenttype:
                miner.minerlevel = minerlevel
                miner.employmenttype = employmenttype
                miner.save(update_fields=['minerlevel', 'employmenttype'])
                updated += 1

        messages.success(request, f'Updated {updated} member{"s" if updated != 1 else ""}.' if updated else 'No changes to save.')
        return redirect('crew_assignments')

    if request.method == 'POST' and request.POST.get('action') == 'assign_basket':
        # Fills a leaderless basket — either a shifter with no home basket at
        # all (sets crewid/shiftertype as their new home, same as always), or
        # an already-busy shifter picking up a second, currently-leaderless
        # basket (mirrors the existing "hold two baskets" pattern Transfer
        # Basket already allows for a promoted Spare Shifter): their own home
        # basket is left untouched, they just also claim this one's roster.
        # Only blocked when the target is busy AND this basket has no
        # existing crew to hand them — nothing to actually put them in
        # charge of, so Transfer Basket is the right tool there instead.
        target = get_object_or_404(User, employeeid=request.POST.get('shifter_id', '').strip(), roleid__accessid__accessid=5, isactive=True)
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        if not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        else:
            claimed = CrewAssignment.objects.filter(
                crewid_id=crewid, shiftertype=shiftertype, shifter__isnull=True, enddate__isnull=True
            ).update(shifter=target)
            is_home_free = not target.crewid_id and not target.shiftertype
            if not is_home_free and not claimed:
                messages.error(
                    request,
                    f'{target.firstname} {target.lastname} already runs a basket, and this one has no existing '
                    f'crew to hand them — use Transfer Basket instead.'
                )
            else:
                if is_home_free:
                    target.crewid_id = crewid
                    target.shiftertype = shiftertype
                    target.save(update_fields=['crewid', 'shiftertype'])
                log_action(request.user, 'Assign Shifter to Basket', 'Employee', target.eid,
                           {'crewid': None, 'shiftertype': None}, {'crewid': crewid, 'shiftertype': shiftertype})
                crew_name = Crews.objects.get(pk=crewid).crewname
                if claimed:
                    messages.success(
                        request,
                        f'{target.firstname} {target.lastname} now runs Crew {crew_name} — {shiftertype} '
                        f'({claimed} existing member{"s" if claimed != 1 else ""} picked up).'
                    )
                else:
                    messages.success(request, f'{target.firstname} {target.lastname} now runs Crew {crew_name} — {shiftertype}.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_assignments')

    if request.method == 'POST' and request.POST.get('action') == 'promote_and_assign_basket':
        # One-step "promote a Miner straight into this vacant basket" —
        # the Grid's version of promote_to_shifter_permanent, so a leaderless
        # basket can be filled by promoting from within the ranks without a
        # separate trip to Shifter/Miner Management.
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=8, isactive=True)
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        if not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        else:
            shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
            target.roleid = shifter_role
            target.minerlevel = 'Staff'
            target.crewid_id = crewid
            target.shiftertype = shiftertype
            target.save(update_fields=['roleid', 'minerlevel', 'crewid', 'shiftertype'])
            claimed = CrewAssignment.objects.filter(
                crewid_id=crewid, shiftertype=shiftertype, shifter__isnull=True, enddate__isnull=True
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
        return redirect('crew_assignments')

    if request.method == 'POST' and request.POST.get('action') == 'promote_and_assign_basket_temporary':
        # Same one-step fill as promote_and_assign_basket above, but lands in
        # Spare Shifter instead of Shift Coordinator — meant to be reversible
        # (Demote later), so it carries the same Lead/1/2 eligibility floor
        # Crew Coverage's own promotion already uses, rather than being open
        # to any Miner the way the permanent version is.
        target = get_object_or_404(
            User, employeeid=request.POST.get('employee_id', '').strip(),
            roleid__accessid__accessid=8, minerlevel__in=['Lead', '1', '2'], isactive=True,
        )
        crewid = request.POST.get('crewid') or None
        shiftertype = request.POST.get('shiftertype') or None
        if not crewid or not shiftertype:
            messages.error(request, 'Select both a crew and a discipline.')
        else:
            spare_role = get_object_or_404(Roles, rolename='Spare Shifter')
            target.roleid = spare_role
            target.crewid_id = crewid
            target.shiftertype = shiftertype
            target.save(update_fields=['roleid', 'crewid', 'shiftertype'])
            claimed = CrewAssignment.objects.filter(
                crewid_id=crewid, shiftertype=shiftertype, shifter__isnull=True, enddate__isnull=True
            ).update(shifter=target)
            log_action(request.user, 'Promote to Spare Shifter', 'Employee', target.eid,
                       {'roleid': None, 'crewid': None, 'shiftertype': None},
                       {'roleid': spare_role.roleid, 'crewid': crewid, 'shiftertype': shiftertype})
            crew_name = Crews.objects.get(pk=crewid).crewname
            messages.success(
                request,
                f'{target.firstname} {target.lastname} temporarily promoted to Spare Shifter and now runs Crew {crew_name} — {shiftertype}'
                + (f' ({claimed} existing member{"s" if claimed != 1 else ""} picked up).' if claimed else '.')
            )

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_assignments')

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
        minerlevel = request.POST.get('minerlevel') or None
        contractid = request.POST.get('contractid') or None
        old_values = {'minerlevel': target.minerlevel, 'contractid': target.contractid_id}
        target.minerlevel = minerlevel
        target.contractid_id = contractid
        target.save(update_fields=['minerlevel', 'contractid'])
        log_action(request.user, 'Edit Level/Contract', 'Employee', target.eid,
                   old_values, {'minerlevel': minerlevel, 'contractid': contractid})
        messages.success(request, f'Updated {target.firstname} {target.lastname}.')

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_assignments')

    if request.method == 'POST' and request.POST.get('action') == 'promote_to_shifter_permanent':
        # Permanent (not Spare) promotion — a deliberate placement decision,
        # so it lives here as its own explicit action rather than on the
        # Grid's drag/assign gestures, which stay scoped to fast, reversible
        # temporary coverage. Open to any Miner — unlike Spare Shifter
        # coverage, this isn't an emergency fill, so no Lead/1/2 floor.
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=8, isactive=True)
        shifter_role = get_object_or_404(Roles, rolename='Shift Coordinator')
        old_values = {'roleid': target.roleid_id, 'minerlevel': target.minerlevel}
        target.roleid = shifter_role
        # Staff/Contract is HR's classification, independent of role — but a
        # newly permanent Shifter is no longer working the Miner-level scale,
        # so it defaults to Staff and stays editable immediately afterward
        # via the Crew Grid's Level/Contract modal (already open to Shifters).
        target.minerlevel = 'Staff'
        target.save(update_fields=['roleid', 'minerlevel'])
        log_action(request.user, 'Promote to Shifter (Permanent)', 'Employee', target.eid,
                   old_values, {'roleid': shifter_role.roleid, 'minerlevel': 'Staff'})
        messages.success(request, f'{target.firstname} {target.lastname} permanently promoted to Shifter.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_assignments')

    if request.method == 'POST' and request.POST.get('action') == 'demote_to_miner_permanent':
        # Vacates rather than disperses: the basket's CrewAssignment rows
        # lose their shifter (shifter=None) but keep employee/positionid/
        # crewid/shiftertype untouched, so the crew stays exactly where it
        # is — the basket just shows "Unassigned" until someone new is
        # placed there (temporary assign, Spare Shifter, or another
        # permanent promotion/transfer all pick the roster back up).
        target = get_object_or_404(User, employeeid=request.POST.get('employee_id', '').strip(), roleid__accessid__accessid=5, isactive=True)
        miner_role = get_object_or_404(Roles, rolename='Underground Mine Operator')
        vacated = CrewAssignment.objects.filter(shifter=target, enddate__isnull=True).update(shifter=None)
        old_values = {'roleid': target.roleid_id, 'crewid': target.crewid_id, 'shiftertype': target.shiftertype}
        target.roleid = miner_role
        target.crewid = None
        target.shiftertype = None
        target.save(update_fields=['roleid', 'crewid', 'shiftertype'])
        log_action(request.user, 'Demote to Miner (Permanent)', 'Employee', target.eid,
                   old_values, {'roleid': miner_role.roleid, 'crewid': None, 'shiftertype': None})
        if vacated:
            messages.success(
                request,
                f'{target.firstname} {target.lastname} demoted to Miner — their basket '
                f'({vacated} member{"s" if vacated != 1 else ""}) is now Unassigned and can be reassigned.'
            )
        else:
            messages.success(request, f'{target.firstname} {target.lastname} demoted to Miner.')
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_assignments')

    return render(request, 'users/crew_assignments.html', {
        'shifters': shifters,
        'miners': miners,
        'crews': Crews.objects.filter(isactive=1),
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
        'minerlevel_choices': User.MINER_LEVEL_CHOICES,
        'employment_type_choices': User.EMPLOYMENT_TYPE_CHOICES,
    })


@login_required(login_url='login')
def position_catalog(request):
    if request.user.access_level != 2:
        return redirect('profile')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            positionname = request.POST.get('positionname', '').strip()
            shiftertype = request.POST.get('shiftertype', '').strip() or None
            if positionname:
                Position.objects.create(positionname=positionname, shiftertype=shiftertype, isactive=1)
                messages.success(request, f'Added position: {positionname}.')
            else:
                messages.error(request, 'Position name is required.')
            return redirect('position_catalog')

        elif action == 'bulk_classify':
            updated = 0
            for position in Position.objects.all():
                shiftertype = request.POST.get(f'shiftertype_{position.positionid}') or None
                isactive = 1 if request.POST.get(f'isactive_{position.positionid}') == 'on' else 0
                if position.shiftertype != shiftertype or position.isactive != isactive:
                    position.shiftertype = shiftertype
                    position.isactive = isactive
                    position.save(update_fields=['shiftertype', 'isactive'])
                    updated += 1
            messages.success(request, f'Updated {updated} position{"s" if updated != 1 else ""}.' if updated else 'No changes to save.')
            return redirect('position_catalog')

    positions = Position.objects.all()
    return render(request, 'users/position_catalog.html', {
        'positions': positions,
        'unclassified_count': positions.filter(isactive=1, shiftertype__isnull=True).count(),
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
    })


@login_required(login_url='login')
def crew_assignment_detail(request, shifter_id):
    if request.user.access_level != 2:
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
    available_employees = User.objects.filter(roleid__accessid__accessid=8, isactive=True).exclude(eid__in=assigned_ids)

    # Every active Miner, for the Replace panel — includes people currently
    # assigned elsewhere (picking one moves them: their old assignment ends
    # automatically), labeled with where they currently are so it's clear
    # which selections are a plain fill vs. a move.
    all_miners = list(User.objects.filter(roleid__accessid__accessid=8, isactive=True).order_by('lastname', 'firstname'))
    active_by_employee = {
        a.employee_id: a for a in CrewAssignment.objects.filter(enddate__isnull=True).select_related('crewid')
    }
    for m in all_miners:
        current = active_by_employee.get(m.eid)
        m.current_assignment_label = f"{current.crewid.crewname if current.crewid else '?'} — {current.shiftertype or '?'}" if current else None

    # Other active shifters, for Transfer Basket's "who receives it" picker.
    other_shifters = User.objects.filter(
        roleid__accessid__accessid=5, isactive=True
    ).exclude(eid=shifter.eid).order_by('lastname', 'firstname')

    # Unclassified positions stay visible as a fallback while the Superintendent
    # is still gradually classifying the catalog (Position Catalog page).
    positions = Position.objects.filter(isactive=1)
    if active_basket:
        positions = positions.filter(Q(shiftertype=active_basket[1]) | Q(shiftertype__isnull=True))

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'bulk_add_members':
            start_date = request.POST.get('startdate')
            employee_ids = request.POST.getlist('employee_ids')
            added = []
            for employee_id in employee_ids:
                employee = get_object_or_404(User, employeeid=employee_id, roleid__accessid__accessid=8, isactive=True)
                position_id = request.POST.get(f'position_{employee_id}') or None
                CrewAssignment.objects.create(
                    shifter=shifter,
                    employee=employee,
                    positionid_id=position_id,
                    startdate=start_date,
                    crewid=active_basket[0] if active_basket else None,
                    shiftertype=active_basket[1] if active_basket else None,
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
                qs.update(enddate=timezone.now().date())
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
                    other_active.update(enddate=timezone.now().date())
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
                    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
                    replacement = User(
                        employeeid=new_employeeid,
                        firstname=new_firstname,
                        lastname=new_lastname,
                        phonenumber=new_phone,
                        roleid=miner_role,
                        isactive=True,
                        hasaccess=True,
                        is_temporary=True,
                        employmenttype='Contract',
                    )
                    replacement.set_password(temp_password)
                    replacement.save()
                    print(f"SMS to {new_phone}: Temp password for {new_firstname} {new_lastname} is {temp_password}")

            if replacement:
                today = timezone.now().date()
                old_assignment.enddate = today
                old_assignment.save(update_fields=['enddate'])

                CrewAssignment.objects.create(
                    shifter=shifter,
                    employee=replacement,
                    positionid=old_assignment.positionid,
                    startdate=today,
                    crewid=old_assignment.crewid,
                    shiftertype=old_assignment.shiftertype,
                )
                position_label = old_assignment.positionid.positionname if old_assignment.positionid else 'the crew'
                if moved_from_elsewhere:
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
                old_role_values = {'roleid': miner.roleid_id, 'minerlevel': miner.minerlevel}
                miner.roleid = shifter_role
                miner.minerlevel = 'Staff'
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
                    shifter=shifter, crewid=active_basket[0], shiftertype=active_basket[1], enddate__isnull=True
                )
                members = list(rows)
                today = timezone.now().date()

                old_values = {'shifter': shifter.eid, 'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1]}
                rows.update(enddate=today)
                CrewAssignment.objects.bulk_create([
                    CrewAssignment(
                        shifter=new_shifter, employee=m.employee, positionid=m.positionid,
                        startdate=today, crewid=active_basket[0], shiftertype=active_basket[1],
                    ) for m in members
                ])

                # If this was the departing shifter's own home basket, clear it —
                # they no longer run it. A shifter transferring away a second
                # (non-home) basket keeps their home identity untouched.
                if shifter.crewid_id == active_basket[0].crewid and shifter.shiftertype == active_basket[1]:
                    shifter.crewid = None
                    shifter.shiftertype = None
                    shifter.save(update_fields=['crewid', 'shiftertype'])

                log_action(request.user, 'Transfer Basket', 'CrewAssignment', shifter.eid,
                           old_values, {'shifter': new_shifter.eid, 'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1]})
                messages.success(
                    request,
                    f'Transferred Crew {active_basket[0].crewname} — {active_basket[1]} '
                    f'({len(members)} member{"s" if len(members) != 1 else ""}) to {new_shifter.firstname} {new_shifter.lastname}.'
                )
                next_url = request.POST.get('next', '').strip()
                if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(next_url)
                return redirect(reverse('crew_assignment_detail', args=[new_shifter.employeeid]))

        elif action == 'start_coverage':
            # Reversible sibling of transfer_basket: moves the same roster
            # rows in place (never ends/recreates them) and never touches
            # this shifter's own home crewid/shiftertype — they stay the
            # basket's nominal owner and the rows come straight back to them
            # when the coverage ends (Crew Coverage's own "end" action).
            covering_shifter_id = request.POST.get('covering_shifter_id', '').strip()
            promote_employee_id = request.POST.get('promote_employee_id', '').strip()
            startdate = request.POST.get('startdate') or timezone.now().date()
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
                    minerlevel__in=['Lead', '1', '2'], isactive=True,
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

            if covering:
                moved = CrewAssignment.objects.filter(
                    shifter=shifter, crewid=active_basket[0], shiftertype=active_basket[1], enddate__isnull=True
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
                return redirect(reverse('crew_assignment_detail', args=[shifter.employeeid]))

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
                if source.crewid_id == active_basket[0].crewid and source.shiftertype == active_basket[1] and source.positionid_id == dest_position_id:
                    messages.warning(request, f'{source.employee.firstname} {source.employee.lastname} is already there.')
                else:
                    today = timezone.now().date()
                    old_values = {'crewid': source.crewid_id, 'shiftertype': source.shiftertype, 'positionid': source.positionid_id}
                    source.enddate = today
                    source.save(update_fields=['enddate'])
                    CrewAssignment.objects.create(
                        shifter=shifter, employee=source.employee, positionid_id=dest_position_id,
                        startdate=today, crewid=active_basket[0], shiftertype=active_basket[1],
                    )
                    log_action(request.user, 'Move Crew Member', 'CrewAssignment', source.employee_id, old_values,
                               {'crewid': active_basket[0].crewid, 'shiftertype': active_basket[1], 'positionid': dest_position_id})
                    messages.success(request, f'Moved {source.employee.firstname} {source.employee.lastname}.')

        redirect_url = reverse('crew_assignment_detail', args=[shifter_id])
        if len(basket_list) > 1 and active_basket:
            redirect_url += f'?basket={active_basket[0].crewid}:{active_basket[1]}'
        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect(redirect_url)

    return render(request, 'users/crew_assignment_detail.html', {
        'shifter': shifter,
        'active_assignments': active_assignments,
        'available_employees': available_employees,
        'all_miners': all_miners,
        'other_shifters': other_shifters,
        'positions': positions,
        'basket_list': basket_list,
        'active_basket': active_basket,
    })


# Discipline bands in the order they appear on the Superintendent's paper/Excel
# sheet, and which Crews columns each band draws from. Development/Production
# are run per single crew (A/B/C/D); Longhole/Logistics are jointly staffed by
# the AB/CD crews, which are already their own real Crews rows (no new schema
# needed — they just render merged across the A/B and C/D columns visually).
CREW_GRID_BANDS = [
    ('Development', ['A', 'B', 'C', 'D']),
    ('Longhole', ['AB', 'CD']),
    ('Logistics', ['AB', 'CD']),
    ('Production', ['A', 'B', 'C', 'D']),
]


@login_required(login_url='login')
def crew_grid(request):
    """Additive planning view mimicking the Superintendent's Excel crew/
    position sheet in one page — a bird's-eye layout over the same
    CrewAssignment/Position data crew_assignment_detail and position_catalog
    already manage. This view itself only ever reads; every mutation (add,
    replace, transfer, move) is submitted, via modal or drag-and-drop, straight
    to crew_assignment_detail's own already-tested POST actions (with a `next`
    field bringing the user back here afterward) — no business logic is
    duplicated here, just the data those modals need to populate themselves."""
    if request.user.access_level != 2:
        return redirect('profile')

    crews_by_name = {c.crewname: c for c in Crews.objects.filter(isactive=1)}

    positions_by_type = {}
    for p in Position.objects.filter(isactive=1, shiftertype__isnull=False).order_by('positionname'):
        positions_by_type.setdefault(p.shiftertype, []).append(p)

    active_assignments = list(
        CrewAssignment.objects.filter(enddate__isnull=True)
        .select_related('employee', 'positionid', 'crewid', 'shifter')
    )

    cell_map = {}
    needs_attention = []
    for a in active_assignments:
        if not a.crewid_id or not a.shiftertype:
            needs_attention.append((a, 'Not linked to a basket yet (missing crew/discipline on the assignment).'))
            continue
        if a.positionid and a.positionid.shiftertype and a.positionid.shiftertype != a.shiftertype:
            needs_attention.append((a, f'Position is classified as {a.positionid.shiftertype}, but this assignment is filed under {a.shiftertype}.'))
        cell_map.setdefault((a.crewid_id, a.shiftertype, a.positionid_id), []).append(a)

    shifters_by_basket = {}
    for u in User.objects.filter(roleid__accessid__accessid=5, isactive=True, crewid__isnull=False, shiftertype__isnull=False):
        shifters_by_basket.setdefault((u.crewid_id, u.shiftertype), u)
    # Live roster data wins over the static home-field match when the two
    # disagree — e.g. a basket under Coverage shows the covering shifter,
    # not the nominal home owner, since the CrewAssignment rows are what's
    # actually true day to day. A leaderless (shifter=None) row never blanks
    # out a home-field match; it only fills a gap or overrides a real one.
    for a in active_assignments:
        if a.crewid_id and a.shiftertype and a.shifter_id:
            shifters_by_basket[(a.crewid_id, a.shiftertype)] = a.shifter

    coverage_by_basket = {
        (c.crewid_id, c.shiftertype): c
        for c in CrewCoverage.objects.filter(enddate__isnull=True, crewid__isnull=False, shiftertype__isnull=False)
        .select_related('home_shifter', 'covering_shifter')
    }

    grid = []
    for label, crewnames in CREW_GRID_BANDS:
        columns = []
        for cn in crewnames:
            crew = crews_by_name.get(cn)
            if not crew:
                continue
            shifter = shifters_by_basket.get((crew.crewid, label))
            columns.append({
                'crew': crew,
                'shifter': shifter,
                'basket': f'{crew.crewid}:{label}',
                # Longhole/Logistics columns are AB/CD, each visually spanning
                # the two single-crew columns they jointly staff.
                'colspan': 2 if cn in ('AB', 'CD') else 1,
                'coverage': coverage_by_basket.get((crew.crewid, label)),
            })

        # Position rows built once per band (not per column) — every column in
        # a band shares the same position list/order, so each row just holds
        # one cell per column, aligned by index. Avoids needing to zip parallel
        # per-column lists back together in the template.
        #
        # A position can be double (triple, ...) staffed in one basket — e.g.
        # 4 Water Management people under one Logistics crew. Rather than
        # stacking names inside a single cell (ambiguous to click or drag),
        # the position gets as many stacked rows as its busiest column needs;
        # the label itself only prints once via rowspan. Columns with fewer
        # occupants just show empty add-slots in the extra rows.
        #
        # AB/CD columns (Longhole/Logistics) are already double-wide (colspan
        # 2) to visually span the two single-crew columns they jointly staff,
        # so there's room to pack 2 occupants side by side per lane row before
        # wrapping to a new one — cutting the vertical growth in half for
        # exactly the columns that are physically wide enough for it. Single
        # A/B/C/D columns stay one-per-row, since there's no spare width there.
        is_paired_band = label in ('Longhole', 'Logistics')
        group_size = 2 if is_paired_band else 1

        position_rows = []
        for position in positions_by_type.get(label, []):
            per_column_occupants = [
                cell_map.get((col['crew'].crewid, label, position.positionid), [])
                for col in columns
            ]
            lane_height = max((-(-len(o) // group_size) for o in per_column_occupants), default=1) or 1
            for slot in range(lane_height):
                cells = []
                for col, occupants in zip(columns, per_column_occupants):
                    group = occupants[slot * group_size:(slot + 1) * group_size]
                    items = list(group) + [None] * (group_size - len(group))
                    cells.append({'col': col, 'items': items})
                position_rows.append({
                    'position': position,
                    'cells': cells,
                    'is_first': slot == 0,
                    'rowspan': lane_height,
                })

        grid.append({'label': label, 'columns': columns, 'position_rows': position_rows})

    # Captain row — one flat row spanning the whole grid, not a per-crew column:
    # just every active Mine Captain (al=4), the same plain roster-query
    # treatment as the Shifters/Room Allocation rows. No attempt to line a
    # captain up under a specific crew column — that link doesn't exist in the
    # schema and isn't being added for this.
    active_captains = User.objects.filter(roleid__accessid__accessid=4, isactive=True).order_by('lastname', 'firstname')

    # Data for the inline Add/Replace/Transfer modals — plain JSON-able lists,
    # rendered via json_script and read by the grid's JS, which populates and
    # points a single shared modal per action type at whichever basket/cell
    # was clicked rather than pre-rendering one form per cell.
    unclassified_positions = list(
        Position.objects.filter(isactive=1, shiftertype__isnull=True).order_by('positionname').values('positionid', 'positionname')
    )
    positions_for_modal = {}
    for label, _ in CREW_GRID_BANDS:
        items = [{'id': p.positionid, 'name': p.positionname} for p in positions_by_type.get(label, [])]
        items += [{'id': p['positionid'], 'name': p['positionname']} for p in unclassified_positions]
        positions_for_modal[label] = items

    assigned_ids = CrewAssignment.objects.filter(enddate__isnull=True).values_list('employee_id', flat=True)
    available_employees = User.objects.filter(
        roleid__accessid__accessid=8, isactive=True
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
        current_label = None
        if current:
            crew_name = current.crewid.crewname if current.crewid else '?'
            current_label = f'{crew_name} — {current.shiftertype or "?"}'
        # minerlevel travels along so the JS can filter to Lead/1/2 for the
        # Spare Shifter (temporary) picker without a second near-duplicate
        # server-side list — the permanent-promotion pickers use the full set.
        all_miners_for_modal.append({
            'employeeid': m.employeeid, 'name': f'{m.firstname} {m.lastname}',
            'current_label': current_label, 'minerlevel': m.minerlevel,
        })

    all_shifters_for_modal = [
        {
            'employeeid': s.employeeid, 'name': f'{s.firstname} {s.lastname}',
            'current_label': f'{s.crewid.crewname} — {s.shiftertype}' if s.crewid_id and s.shiftertype else None,
        }
        for s in User.objects.filter(roleid__accessid__accessid=5, isactive=True).select_related('crewid').order_by('lastname', 'firstname')
    ]

    # Contract Code choices for the Edit Level/Contract modal, keyed by Level —
    # a contract tagged to zero levels is still unclassified, not invalid, so
    # (mirroring Position's own shiftertype fallback) it stays offered under
    # every level rather than disappearing once real classification starts.
    unclassified_contracts = [
        {'id': c['contractid'], 'label': f"{c['contractcode']} — {c['contracttitle']}"}
        for c in Contract.objects.filter(isactive=1, levels__isnull=True).order_by('contractcode').values('contractid', 'contractcode', 'contracttitle')
    ]
    contracts_for_modal = {}
    for level in MinerLevel.objects.all():
        items = [
            {'id': c.contractid, 'label': f'{c.contractcode} — {c.contracttitle}'}
            for c in Contract.objects.filter(isactive=1, levels=level).order_by('contractcode')
        ]
        contracts_for_modal[level.levelcode] = items + unclassified_contracts

    return render(request, 'users/crew_grid.html', {
        'grid': grid,
        'needs_attention': needs_attention,
        'main_crews': ['A', 'B', 'C', 'D'],
        'active_captains': active_captains,
        'positions_for_modal': positions_for_modal,
        'available_employees_for_modal': available_employees_for_modal,
        'all_miners_for_modal': all_miners_for_modal,
        'all_shifters_for_modal': all_shifters_for_modal,
        'contracts_for_modal': contracts_for_modal,
        'minerlevel_choices': User.MINER_LEVEL_CHOICES,
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


@login_required(login_url='login')
def crew_coverage(request):
    # Assigning/ending coverage and promoting a Miner are a Mine Captain's job
    # day-to-day, but the Superintendent can do the same here directly —
    # they're the one who can already do it via the Crew Grid/Shifter & Miner
    # Management anyway, so this stops being read-only for them too.
    if request.user.access_level not in (2, 4):
        return redirect('profile')

    can_manage = request.user.access_level in (2, 4)
    today = timezone.now().date()

    home_shifters = User.objects.filter(
        roleid__rolename='Shift Coordinator', isactive=True
    ).order_by('lastname', 'firstname')
    covering_shifters = User.objects.filter(
        roleid__accessid__accessid=5, isactive=True
    ).order_by('lastname', 'firstname')
    # Lead, Level 1, and Level 2 miners are eligible for Spare Shifter coverage —
    # Levels 3/4 are recorded on the full seniority scale but never offered here.
    miner_candidates = User.objects.filter(
        roleid__accessid__accessid=8, minerlevel__in=['Lead', '1', '2'], isactive=True
    ).order_by('lastname', 'firstname') if can_manage else User.objects.none()

    if request.method == 'POST' and can_manage:
        action = request.POST.get('action')

        if action == 'promote':
            miner_id = request.POST.get('miner')
            shiftertype = request.POST.get('shiftertype')
            crewid = request.POST.get('crewid')
            if miner_id and shiftertype and crewid:
                miner = get_object_or_404(User, employeeid=miner_id, roleid__accessid__accessid=8)
                spare_role = get_object_or_404(Roles, rolename='Spare Shifter')
                # employmenttype is NOT forced to Contract here — not every Miner
                # promoted to Spare Shifter is hourly labor. Whatever their real
                # classification already is (Staff or Contract) carries straight
                # through, so the existing self-billing/My-Pay-History gates
                # (which key off employmenttype) keep behaving correctly for
                # whichever kind of Spare Shifter this actually is.
                old_values = {'roleid': miner.roleid_id}
                miner.roleid = spare_role
                miner.shiftertype = shiftertype
                miner.crewid_id = crewid
                miner.hasaccess = True
                miner.save()
                log_action(request.user, 'Promote to Spare Shifter', 'Employee', miner.eid,
                           old_values, {'roleid': spare_role.roleid})

        elif action == 'add':
            # The form submits employeeid (matching every other select on this
            # page), not the numeric eid these FKs actually store — resolve
            # through employeeid rather than assigning the raw POST value.
            covering_id = request.POST.get('covering_shifter')
            home_id = request.POST.get('home_shifter')
            startdate = request.POST.get('startdate')
            notes = request.POST.get('notes') or None
            if covering_id and home_id and startdate and covering_id != home_id:
                covering_shifter = get_object_or_404(User, employeeid=covering_id)
                home_shifter = get_object_or_404(User, employeeid=home_id)
                # Move the home shifter's own basket roster onto the covering
                # shifter in place (never end/recreate the rows) so the Grid
                # actually reflects who's running it day to day — mirrors
                # what the Grid's own Start Coverage action does, so either
                # entry point behaves the same way. Only when there's an
                # unambiguous home basket to move; a home shifter with no
                # plain home crewid/shiftertype (running only a secondary
                # basket) just gets a plain coverage record, as before.
                moved = 0
                if home_shifter.crewid_id and home_shifter.shiftertype:
                    moved = CrewAssignment.objects.filter(
                        shifter=home_shifter, crewid_id=home_shifter.crewid_id,
                        shiftertype=home_shifter.shiftertype, enddate__isnull=True,
                    ).update(shifter=covering_shifter)
                CrewCoverage.objects.create(
                    covering_shifter=covering_shifter,
                    home_shifter=home_shifter,
                    crewid_id=home_shifter.crewid_id if moved else None,
                    shiftertype=home_shifter.shiftertype if moved else None,
                    startdate=startdate,
                    notes=notes,
                    assignedby=request.user,
                )

        elif action == 'end':
            coverage_id = request.POST.get('coverage_id')
            coverage = get_object_or_404(CrewCoverage, coverageid=coverage_id)
            coverage.enddate = today
            coverage.save()

            covering = coverage.covering_shifter
            home = coverage.home_shifter

            # Hand the roster back — Start Coverage moves the existing
            # CrewAssignment rows in place rather than ending/recreating
            # them, so ending it just reverses that same pointer. A legacy
            # coverage record predating crewid/shiftertype never moved
            # anything, so there's nothing to hand back here either.
            if coverage.crewid_id and coverage.shiftertype:
                CrewAssignment.objects.filter(
                    shifter=covering, crewid_id=coverage.crewid_id,
                    shiftertype=coverage.shiftertype, enddate__isnull=True,
                ).update(shifter=home)

            still_covering_elsewhere = CrewCoverage.objects.filter(
                covering_shifter=covering, enddate__isnull=True
            ).exclude(pk=coverage.pk).exists()
            if not still_covering_elsewhere and covering.roleid.rolename == 'Spare Shifter':
                # Coverage never touches CrewAssignment — but nothing stops a
                # Spare Shifter from also picking up a real basket via Transfer
                # Basket while promoted. Reverting them to Miner in that state
                # would leave that basket's roster pointing at someone
                # crew_assignment_detail can no longer resolve (it requires
                # al=5) — so hold the role reversion until it's been moved.
                has_active_basket = CrewAssignment.objects.filter(shifter=covering, enddate__isnull=True).exists()
                if has_active_basket:
                    messages.warning(
                        request,
                        f'Coverage ended, but {covering.firstname} {covering.lastname}\'s role was NOT reverted — '
                        f'they still run an active basket directly. Transfer it to another shifter first, then '
                        f'revert their role via System Admin.'
                    )
                else:
                    miner_role = get_object_or_404(Roles, rolename='Underground Mine Operator')
                    # employmenttype is left untouched on reversion too, symmetric
                    # with promotion — it was never forced to Contract, so there's
                    # nothing to force back.
                    old_values = {'roleid': covering.roleid_id}
                    covering.roleid = miner_role
                    covering.shiftertype = None
                    covering.crewid = None
                    covering.save()
                    log_action(request.user, 'Revert Spare Shifter to Miner', 'Employee', covering.eid,
                               old_values, {'roleid': miner_role.roleid})

        next_url = request.POST.get('next', '').strip()
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect('crew_coverage')

    active_coverages = CrewCoverage.objects.filter(
        enddate__isnull=True
    ).select_related('covering_shifter', 'home_shifter', 'assignedby')

    past_coverages = CrewCoverage.objects.filter(
        enddate__isnull=False
    ).select_related('covering_shifter', 'home_shifter').order_by('-enddate')[:20]

    return render(request, 'users/crew_coverage.html', {
        'can_manage': can_manage,
        'home_shifters': home_shifters,
        'covering_shifters': covering_shifters,
        'miner_candidates': miner_candidates,
        'shiftertype_choices': User.SHIFTER_TYPE_CHOICES,
        'crews': Crews.objects.all().order_by('crewname'),
        'active_coverages': active_coverages,
        'past_coverages': past_coverages,
        'today': today,
    })