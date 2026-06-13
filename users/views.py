from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from users.forms import UserLoginForm
from users.models import User
from django.contrib.auth.decorators import login_required
import random
import string
import os
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from timesheets.models import MainHeader, MainEntry, OperationsHeader



def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
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
    return render(request, 'user_list.html', {'users': users})


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

    if al == 3:  # Supervisor
        subordinates = User.objects.filter(supervisorid=user)
        awaiting_count = MainHeader.objects.filter(employeeid__in=subordinates, overallstatus='Submitted').count()
        in_progress_count = MainHeader.objects.filter(employeeid__in=subordinates, overallstatus='In Progress').count()
        completed_count = MainHeader.objects.filter(employeeid__in=subordinates, overallstatus='Completed').count()
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
            employeeid__in=direct_reports, overallstatus='Completed'
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