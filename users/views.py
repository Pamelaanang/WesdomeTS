from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from users.forms import UserLoginForm
from users.models import User, CrewAssignment, Roles
from django.contrib.auth.decorators import login_required
import random
import string
import os
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from timesheets.models import MainHeader, MainEntry, OperationsHeader
from django.db.models import Count


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
        return redirect('home')
    users = User.objects.select_related('roleid__departmentid').order_by('roleid__departmentid__departmentname', 'lastname')
    roles = Roles.objects.select_related('departmentid').order_by('departmentid__departmentname', 'rolename')
    active_supervisors = User.objects.filter(isactive=True).select_related('roleid').order_by('lastname', 'firstname')
    return render(request, 'user_list.html', {
        'users': users,
        'roles': roles,
        'active_supervisors': active_supervisors,
    })


@login_required(login_url='login')
def generate_password(request, employeeid):
    if request.user.access_level != 1:
        return redirect('home')
    
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
            return redirect('home')
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
            overallstatus='Completed', ohapprovedat_sup__year=today.year, ohapprovedat_sup__month=today.month
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
        subordinates = User.objects.filter(supervisorid=user)
        awaiting_count = MainHeader.objects.filter(employeeid__in=subordinates, overallstatus='Submitted').count()
        in_progress_count = MainHeader.objects.filter(employeeid__in=subordinates, overallstatus='In Progress').count()
        completed_count = MainHeader.objects.filter(
            employeeid__in=subordinates, overallstatus='Completed', completedat__year=today.year, completedat__month=today.month
            ).count()
        oldest_waiting = MainHeader.objects.filter(
            employeeid__in=subordinates, overallstatus='Submitted'
        ).order_by('submittedat').first()

        return render(request, 'users/profile.html', {
            'today': today,
            'awaiting_count': awaiting_count,
            'in_progress_count': in_progress_count,
            'completed_count': completed_count,
            'oldest_waiting': oldest_waiting,
        })

    elif al == 2:  # Superintendent
        direct_reports = User.objects.filter(supervisorid=user)
        personal_pending = MainHeader.objects.filter(
            employeeid__in=direct_reports, overallstatus__in=['Submitted', 'In Progress']
        ).count()
        personal_completed = MainHeader.objects.filter(
            employeeid__in=direct_reports, overallstatus='Completed', completedat__year=today.year, completedat__month=today.month
        ).count()
        shifters = User.objects.filter(supervisorid__in=direct_reports)
        ops_pending_super = OperationsHeader.objects.filter(
            shifterid__in=shifters, overallstatus='In Progress'
        ).count()
        ops_completed = OperationsHeader.objects.filter(
            shifterid__in=shifters, overallstatus='Completed'
        ).count()

        return render(request, 'users/profile.html', {
            'today': today,
            'personal_pending': personal_pending,
            'personal_completed': personal_completed,
            'ops_pending_super': ops_pending_super,
            'ops_completed': ops_completed,
        })

    elif al == 4:  # Mine Captain
        draft_count = MainHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        pending_count = MainHeader.objects.filter(employeeid=user, overallstatus='Submitted').count()
        latest_header = MainHeader.objects.filter(
            employeeid=user, overallstatus='Submitted'
        ).order_by('-mainheaderid').first()
        approved_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Approved').count() if latest_header else 0
        rejected_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Rejected').count() if latest_header else 0
        shifters = User.objects.filter(supervisorid=user)
        ops_pending_captain = OperationsHeader.objects.filter(
            shifterid__in=shifters, overallstatus='Submitted'
        ).count()
        ops_forwarded = OperationsHeader.objects.filter(
            shifterid__in=shifters, overallstatus='In Progress'
        ).count()

        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'ops_pending_captain': ops_pending_captain,
            'ops_forwarded': ops_forwarded,
        })

    elif al == 5:  # Shifter
        draft_count = MainHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        pending_count = MainHeader.objects.filter(employeeid=user, overallstatus='Submitted').count()
        latest_header = MainHeader.objects.filter(
            employeeid=user, overallstatus='Submitted'
        ).order_by('-mainheaderid').first()
        approved_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Approved').count() if latest_header else 0
        rejected_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Rejected').count() if latest_header else 0
        ops_draft = OperationsHeader.objects.filter(shifterid=user, overallstatus='Draft').count()
        ops_submitted = OperationsHeader.objects.filter(shifterid=user, overallstatus='Submitted').count()
        ops_in_progress = OperationsHeader.objects.filter(shifterid=user, overallstatus='In Progress').count()
        ops_completed = OperationsHeader.objects.filter(shifterid=user, overallstatus='Completed').count()
        
        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'ops_draft': ops_draft,
            'ops_submitted': ops_submitted,
            'ops_in_progress': ops_in_progress,
            'ops_completed': ops_completed,
        })
    
    elif al == 7:  # Payroll
        maintenance_completed = MainHeader.objects.filter(
            overallstatus='Completed',
            completedat__year=today.year,
            completedat__month=today.month
        ).count()
        ops_crew_completed = OperationsHeader.objects.filter(
            overallstatus='Completed',
            ohapprovedat_sup__year=today.year,
            ohapprovedat_sup__month=today.month
        ).count()
        return render(request, 'users/profile.html', {
            'today': today,
            'maintenance_completed': maintenance_completed,
            'ops_crew_completed': ops_crew_completed,
        })

    else:  # Employee (6) and anyone else
        draft_count = MainHeader.objects.filter(employeeid=user, overallstatus='Draft').count()
        pending_count = MainHeader.objects.filter(employeeid=user, overallstatus='Submitted').count()
        latest_header = MainHeader.objects.filter(
            employeeid=user, overallstatus='Submitted'
        ).order_by('-mainheaderid').first()
        approved_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Approved').count() if latest_header else 0
        rejected_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Rejected').count() if latest_header else 0
        return render(request, 'users/profile.html', {
            'today': today,
            'draft_count': draft_count,
            'pending_count': pending_count,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
        })

@login_required(login_url='login')
def upload_profile_photo(request):
    if request.method == 'POST' and request.FILES.get('profile_photo'):
        profile_photo = request.FILES['profile_photo']
        ext = profile_photo.name.rsplit('.', 1)[-1].lower()

        if ext in ['jpg', 'jpeg', 'png', 'webp']:
            filename = f"profile_{request.user.employeeid}.{ext}"
            save_path = os.path.join(settings.MEDIA_ROOT, 'profile_photos', filename)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb+') as destination:
                for chunk in profile_photo.chunks(): 
                    destination.write(chunk)
            
            request.user.profilepic = f"profile_photos/{filename}"
            request.user.save()

    return redirect('profile')


@login_required(login_url='login')
def add_employee(request):
    if request.user.access_level != 1:
        return redirect('home')

    if request.method == 'POST':
        employeeid   = request.POST.get('employeeid', '').strip()
        firstname    = request.POST.get('firstname', '').strip()
        lastname     = request.POST.get('lastname', '').strip()
        phonenumber  = request.POST.get('phonenumber', '').strip()
        roleid       = request.POST.get('roleid', '').strip()
        supervisorid = request.POST.get('supervisorid', '').strip() or None
        hasaccess    = request.POST.get('hasaccess') == 'on'

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
            )
            new_user.set_password(temp_password)
            new_user.save()
            print(f"SMS to {phonenumber}: Temp password for {firstname} {lastname} is {temp_password}")
            messages.success(request, f"{firstname} {lastname} added successfully.")

    return redirect('user_list')


@login_required(login_url='login')
def replace_employee(request, employeeid):
    if request.user.access_level != 1:
        return redirect('home')

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