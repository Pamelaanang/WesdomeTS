from email import header
from urllib import request

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from users.models import User
from .models import MainHeader, MainEntry, Crews, Workcategory
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max

# Create your views here.
@login_required(login_url = 'login')
def new_timesheet(request):
    two_months_ago = timezone.now() - timezone.timedelta(days=60)
    MainHeader.objects.filter(employeeid=request.user, overallstatus='Draft', startedat__lt=two_months_ago).delete()
    
    existing = MainHeader.objects.filter(employeeid=request.user, overallstatus='Draft').first()
    if existing:
        return redirect('add_entry', pk=existing.mainheaderid)
    header = MainHeader.objects.create(employeeid=request.user)
    return redirect('add_entry', pk=header.mainheaderid)

@login_required(login_url = 'login')
def add_entry(request, pk):
    header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid=request.user)
    days_remaining = 60 - (timezone.now() - header.startedat).days

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_entry':
            entryid = request.POST.get('entryid')
            if entryid:
                entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                entry.workcategoryid_id = request.POST.get('workcategoryid')
                entry.sapworkid = request.POST.get('sapworkid') or None
                entry.shifttype = request.POST.get('shifttype')
                entry.hoursworked = request.POST.get('hoursworked')
                entry.startdate = request.POST.get('startdate')
                entry.entrydescription = request.POST.get('entrydescription') or None
                entry.save()
            else:
                MainEntry.objects.create(
                    mainheaderid = header,
                    workcategoryid_id = request.POST.get('workcategoryid'),
                    sapworkid = request.POST.get('sapworkid') or None,
                    shifttype = request.POST.get('shifttype'),
                    hoursworked = request.POST.get('hoursworked'),
                    startdate = request.POST.get('startdate'),
                    entrydescription = request.POST.get('entrydescription') or None
                )

        elif action == 'update_crew':
            header.crewid_id = request.POST.get('crewid') or None
            header.save()

        elif action == 'delete_entry': 
            entry_id = request.POST.get('entryid')
            MainEntry.objects.filter(mainentryid=entry_id, mainheaderid=header).delete()
        
        elif action == 'submit_timesheet':
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            MainEntry.objects.filter(mainheaderid=header).update(linestatus='New')
            return redirect('profile')
        
        return redirect('add_entry', pk=header.mainheaderid)
    
    entries = MainEntry.objects.filter(mainheaderid=header)
    crews = Crews.objects.all()
    workcategories = Workcategory.objects.all()
    hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0

    return render(request, 'timesheets/add_entry.html',{
        'header': header,
        'entries': entries,
        'crews': crews,
        'workcategories': workcategories,
        'today': timezone.now().date(),
        'hours': hours,
        'days_remaining': days_remaining
    })

@login_required(login_url='login')
def approval_inbox(request):
    if request.user.access_level != 3:
        return redirect('home')
    
    subordinates = User.objects.filter(supervisorid=request.user)
    pending = MainHeader.objects.filter(
        employeeid__in=subordinates,
        overallstatus__in=['Submitted', 'In Progress']
    ).select_related('employeeid__roleid').annotate(
        entry_count=Count('mainentry'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate')
    ).order_by('employeeid__lastname', 'employeeid__firstname', 'date_from')
    cards_waiting = pending.count()
                     
    return render(request, 'timesheets/approval_inbox.html', {'pending': pending, 'cards_waiting': cards_waiting})



@login_required(login_url = 'login')
def review_timesheet(request, pk):
    if request.user.access_level != 3:
        return redirect('profile')
    
    subordinates = User.objects.filter(supervisorid=request.user)
    header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid__in=subordinates)

    if header.overallstatus == 'Completed':
        return redirect('approval_inbox')

    entries = MainEntry.objects.filter(mainheaderid=header)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
             entryid = request.POST.get('entryid')
             if entryid:
                 entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                 entry.linestatus = 'Approved'
                 entry.approvedat = timezone.now()
                 entry.supervisornote = request.POST.get('supervisornote') or None
                 entry.approvedby = request.user
                 entry.save()
                 header.overallstatus = 'In Progress'
                 header.save()

        elif action == 'reject':
             entryid = request.POST.get('entryid')
             if entryid:
                 entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                 entry.linestatus = 'Rejected'
                 entry.approvedat = timezone.now()
                 entry.supervisornote = request.POST.get('supervisornote') or None
                 entry.approvedby = request.user
                 entry.save()
                 header.overallstatus = 'In Progress'
                 header.save()
            

        elif action == 'finish_review':
            header.overallstatus = 'Completed'
            header.save()
            return redirect('approval_inbox')
    
        return redirect('review_timesheet', pk=header.mainheaderid)
    
    return render(request, 'timesheets/review_timesheet.html', {'header': header, 'entries': entries})


