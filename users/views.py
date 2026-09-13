from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.conf import settings
from users.forms import UserLoginForm
from users.models import User, CrewAssignment, Roles, Position, CrewCoverage, Department
from django.contrib.auth.decorators import login_required
import random
import string
import os
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from timesheets.models import MainHeader, MainEntry, OperationsHeader, OperationsEntry, BusinessHeader, BusinessEntry, Crews, Contract, Account
from django.db.models import Count, Q, Sum
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

        if not all([new_employeeid, firstname, lastname, phonenumber, roleid]):
            messages.error(request, "All required fields must be filled.")
        elif User.objects.exclude(eid=employee.eid).filter(employeeid=new_employeeid).exists():
            messages.error(request, f"Employee ID '{new_employeeid}' is already in use.")
        elif supervisorid == str(employee.eid):
            messages.error(request, "An employee cannot supervise themselves.")
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

    return render(request, 'users/crew_assignments.html', {
        'shifters': shifters,
        'miners': miners,
        'crews': Crews.objects.filter(isactive=1),
        'shifter_type_choices': User.SHIFTER_TYPE_CHOICES,
        'minerlevel_choices': User.MINER_LEVEL_CHOICES,
        'employment_type_choices': User.EMPLOYMENT_TYPE_CHOICES,
    })


@login_required(login_url='login')
def crew_assignment_detail(request, shifter_id):
    if request.user.access_level != 2:
        return redirect('profile')

    shifter = get_object_or_404(User, employeeid=shifter_id, roleid__accessid__accessid=5, isactive=True)

    active_assignments = CrewAssignment.objects.filter(
        shifter=shifter,
        enddate__isnull=True
    ).select_related('employee')

    assigned_ids = CrewAssignment.objects.filter(enddate__isnull=True).values_list('employee_id', flat=True)
    available_employees = User.objects.filter(roleid__accessid__accessid=8, isactive=True).exclude(eid__in=assigned_ids)

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

        return redirect('crew_assignment_detail', shifter_id=shifter_id)

    positions = Position.objects.filter(isactive=1)

    return render(request, 'users/crew_assignment_detail.html', {
        'shifter': shifter,
        'active_assignments': active_assignments,
        'available_employees': available_employees,
        'positions': positions,
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
    # Assigning/ending coverage and promoting a Miner are a Mine Captain's job;
    # the Superintendent keeps read-only visibility into who's covering whom.
    if request.user.access_level not in (2, 4):
        return redirect('profile')

    can_manage = request.user.access_level == 4
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
                old_values = {'roleid': miner.roleid_id, 'employmenttype': miner.employmenttype}
                miner.roleid = spare_role
                miner.employmenttype = 'Contract'
                miner.shiftertype = shiftertype
                miner.crewid_id = crewid
                miner.hasaccess = True
                miner.save()
                log_action(request.user, 'Promote to Spare Shifter', 'Employee', miner.eid,
                           old_values, {'roleid': spare_role.roleid, 'employmenttype': 'Contract'})

        elif action == 'add':
            covering_id = request.POST.get('covering_shifter')
            home_id = request.POST.get('home_shifter')
            startdate = request.POST.get('startdate')
            notes = request.POST.get('notes') or None
            if covering_id and home_id and startdate and covering_id != home_id:
                CrewCoverage.objects.create(
                    covering_shifter_id=covering_id,
                    home_shifter_id=home_id,
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
            still_covering_elsewhere = CrewCoverage.objects.filter(
                covering_shifter=covering, enddate__isnull=True
            ).exclude(pk=coverage.pk).exists()
            if not still_covering_elsewhere and covering.roleid.rolename == 'Spare Shifter':
                miner_role = get_object_or_404(Roles, rolename='Underground Mine Operator')
                old_values = {'roleid': covering.roleid_id, 'employmenttype': covering.employmenttype}
                covering.roleid = miner_role
                covering.employmenttype = 'Staff'
                covering.shiftertype = None
                covering.crewid = None
                covering.save()
                log_action(request.user, 'Revert Spare Shifter to Miner', 'Employee', covering.eid,
                           old_values, {'roleid': miner_role.roleid, 'employmenttype': 'Staff'})

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