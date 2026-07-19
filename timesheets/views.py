from email import header
from urllib import request

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from users.models import User, Department
from .models import MainHeader, MainEntry, Crews, Workcategory, LeaveType
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max, Q

# Create your views here.
@login_required(login_url = 'login')
def new_timesheet(request):
    two_months_ago = timezone.now() - timezone.timedelta(days=60)
    MainHeader.objects.filter(employeeid=request.user, overallstatus='Draft', startedat__lt=two_months_ago).delete()
    
    now = timezone.now()
    drafts_this_month = MainHeader.objects.filter(
        employeeid=request.user, 
        overallstatus='Draft', 
        startedat__year=now.year, 
        startedat__month=now.month
    ).count()

    if drafts_this_month >= 3:
        messages.warning(request, 'You have reached the maximum of 3 drafts this month. Please continue a previous draft.')
        return redirect('my_drafts')

    header = MainHeader.objects.create(employeeid=request.user)
    return redirect('add_entry', pk=header.mainheaderid)

@login_required(login_url = 'login')
def add_entry(request, pk):
    header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid=request.user)
    if header.overallstatus != 'Draft':
        return redirect('profile')
    days_remaining = 60 - (timezone.now() - header.startedat).days

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_entry':
                category_selection = request.POST.get('category_selection', '')
                workcategoryid = None
                leavetypeid = None
                if category_selection.startswith('wc_'):
                    workcategoryid = category_selection[3:]  # Extract the ID after 'wc_'
                elif category_selection.startswith('lt_'):
                    leavetypeid = category_selection[3:]  # Extract the ID after 'lt_'

                entryid = request.POST.get('entryid')
                if entryid:
                    entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                    entry.workcategoryid_id = workcategoryid
                    entry.leavetypeid_id = leavetypeid
                    entry.sapworkid = request.POST.get('sapworkid') or None
                    entry.shifttype = request.POST.get('shifttype')
                    entry.hoursworked = request.POST.get('hoursworked')
                    entry.startdate = request.POST.get('startdate')
                    entry.entrydescription = request.POST.get('entrydescription') or None
                    entry.save()
                else:
                    MainEntry.objects.create(
                        mainheaderid = header,
                        workcategoryid_id = workcategoryid,
                        leavetypeid_id = leavetypeid,
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
            if not MainEntry.objects.filter(mainheaderid=header).exists():
                return redirect('add_entry', pk=header.mainheaderid)    
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            MainEntry.objects.filter(mainheaderid=header).update(linestatus='New')
            return redirect('profile')
        
        return redirect('add_entry', pk=header.mainheaderid)
        
    entries = MainEntry.objects.filter(mainheaderid=header)
    crews = Crews.objects.all()
    workcategories = Workcategory.objects.all()
    leavetypes = LeaveType.objects.filter(isactive=1)
    hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0

    return render(request, 'timesheets/add_entry.html',{
        'header': header,
        'entries': entries,
        'crews': crews,
        'workcategories': workcategories,
        'leavetypes': leavetypes,
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
    empdate_submitted = header.submittedat

    if header.overallstatus == 'Completed':
        return redirect('approval_inbox')

    entries = MainEntry.objects.filter(mainheaderid=header)
    total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    hours_approved = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0

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
            header.completedat = timezone.now()
            header.save()
            return redirect('approval_inbox')
    
        return redirect('review_timesheet', pk=header.mainheaderid)
    
    has_unreviewed = entries.filter(linestatus='New').exists()
    
    return render(request, 'timesheets/review_timesheet.html', {
    'header': header, 
    'entries': entries, 
    'empdate_submitted': empdate_submitted, 
    'total_hours': total_hours, 
    'hours_approved': hours_approved,
    'has_unreviewed': has_unreviewed
})


@login_required(login_url='login')
def payroll_unprocessed(request):
    if request.user.access_level != 7:
        return redirect('profile')
 
    departments = Department.objects.filter(isactive=1).annotate(
    unpaid_count=Count(
        'roles__user__mainheader', 
            filter=Q(
                roles__user__mainheader__overallstatus='Completed',
                roles__user__mainheader__paidat__isnull=True,
                roles__user__mainheader__mainentry__linestatus='Approved'
                ),
                distinct=True
            )
    )

    
    return render(request, 'timesheets/payroll_unprocessed.html', {'departments': departments})


@login_required(login_url='login')
def payroll_unprocessed_dept(request, dept_id):
    if request.user.access_level != 7:
        return redirect('profile')

    dept = get_object_or_404(Department, departmentid=dept_id)
    employees = User.objects.filter(roleid__departmentid=dept_id, isactive=True)

    submissions = MainHeader.objects.filter(
        employeeid__in=employees,
        overallstatus='Completed',
        paidat__isnull=True
    ).select_related('employeeid').annotate(
        entry_count=Count('mainentry', filter=Q(mainentry__linestatus='Approved')),
        total_hours=Sum('mainentry__hoursworked', filter=Q(mainentry__linestatus='Approved')),
        date_from=Min('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
        date_to=Max('mainentry__startdate', filter=Q(mainentry__linestatus='Approved'))
    ).filter(entry_count__gt=0).order_by('employeeid__lastname', '-submittedat')

    return render(request, 'timesheets/payroll_unprocessed_dept.html', {
        'dept': dept,
        'submissions': submissions
    })
  

@login_required(login_url='login')
def payroll_departments(request):
    if request.user.access_level != 7:
        return redirect('profile')
    else:
        departments = Department.objects.filter(isactive=1)

        return render(request, 'timesheets/payroll_departments.html', {'departments': departments})
    

@login_required(login_url='login')
def payroll_unprocessed_review(request, dept_id, pk):
    if request.user.access_level != 7:
        return redirect('profile')

    dept = get_object_or_404(Department, departmentid=dept_id)
    header = get_object_or_404(
        MainHeader, 
        mainheaderid=pk, 
        employeeid__roleid__departmentid=dept_id
        )

    if header.overallstatus != 'Completed':
        return redirect('payroll_unprocessed_dept', dept_id=dept_id)

    entries = MainEntry.objects.filter(mainheaderid=header, linestatus='Approved').select_related('workcategoryid', 'leavetypeid')
    total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'mark_as_paid':
            header.paidat = timezone.now()
            header.paidby = request.user
            header.save()
            messages.success(request, f'Payment for {header.employeeid.firstname} {header.employeeid.lastname} marked as complete.')
            return redirect('payroll_unprocessed_dept', dept_id=dept_id)

        elif action == 'mark_as_unpaid':
            header.paidat = None
            header.paidby = None
            header.save()
            return redirect('payroll_unprocessed_dept', dept_id=dept_id)

    return render(request, 'timesheets/payroll_unprocessed_review.html', {
        'dept': dept,
        'header': header,
        'entries': entries,
        'total_hours': total_hours
    })



@login_required(login_url='login')
def payroll_processed(request):
    if request.user.access_level != 7:
        return redirect('profile')

    six_months_ago = timezone.now() - timezone.timedelta(days=180)

    employees = User.objects.filter(
    mainheader__paidat__gte=six_months_ago,
    mainheader__paidat__isnull=False,
    isactive=True
    ).distinct().select_related('roleid__departmentid')

    return render(request, 'timesheets/payroll_processed.html', {
        'employees': employees
    })


@login_required(login_url='login')
def payroll_processed_employee(request, employee_id):
    if request.user.access_level != 7:
        return redirect('profile')

    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    six_months_ago = timezone.now() - timezone.timedelta(days=180)

    processed_timesheets = MainHeader.objects.filter(
        employeeid=employee,
        paidat__gte=six_months_ago,
        paidat__isnull=False
    ).select_related('employeeid').annotate(
        entry_count=Count('mainentry', filter=Q(mainentry__linestatus='Approved')),
        total_hours=Sum('mainentry__hoursworked', filter=Q(mainentry__linestatus='Approved')),
        date_from=Min('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
        date_to=Max('mainentry__startdate', filter=Q(mainentry__linestatus='Approved'))
    ).filter(entry_count__gt=0).order_by('-paidat')

    return render(request, 'timesheets/payroll_processed_employee.html', {
        'employee': employee,
        'processed_timesheets': processed_timesheets
    })


@login_required(login_url='login')
def my_drafts(request):
    drafts = MainHeader.objects.filter(employeeid=request.user, overallstatus='Draft').annotate(
        entry_count=Count('mainentry'),
        total_hours=Sum('mainentry__hoursworked'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate')
    ).order_by('-startedat')

    return render(request, 'timesheets/my_drafts.html', {'drafts': drafts})