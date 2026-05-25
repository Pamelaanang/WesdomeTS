from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import MainHeader, Crews

# Create your views here.
@login_required
def new_timesheet(request):
    header = MainHeader.objects.create(employeeid=request.user)
    return redirect('add_entry', pk=header.mainheaderid)


