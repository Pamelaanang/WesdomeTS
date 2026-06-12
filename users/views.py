from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from users.forms import UserLoginForm
from users.models import User
from django.contrib.auth.decorators import login_required
import random
import string
from django.utils import timezone
from django.contrib.auth import update_session_auth_hash
from timesheets.models import MainHeader, MainEntry


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
    user =request.user

    draft_count = MainHeader.objects.filter(employeeid=user, overallstatus='Draft').count()

    pending_count = MainHeader.objects.filter(employeeid=user, overallstatus='Submitted').count()

    latest_header = MainHeader.objects.filter(employeeid=user, overallstatus='Submitted').order_by('-mainheaderid').first()

    approved_count = 0 
    rejected_count = 0

    if latest_header:
        approved_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Approved').count()
        rejected_count = MainEntry.objects.filter(mainheaderid=latest_header, linestatus='Rejected').count()

    return render(request, 'users/profile.html', {
        'today': timezone.now().date(),
        'draft_count': draft_count,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
    })
