from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from users.forms import UserLoginForm
from users.models import User

# Create your views here.
def design_tester(request):
    # This renders your base.html directly so you can see the CSS/Nav
    return render(request, "base.html")

def login_view(request):
    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.is_temporary:
                return redirect('password_reset')
            return redirect('home')
    else:
        form = UserLoginForm(request)
    
    return render(request, 'login.html', {'form': form})