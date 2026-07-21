from email import header
from urllib import request

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from users.models import User, Department, CrewAssignment
from .models import MainHeader, MainEntry, Crews, Workcategory, LeaveType, OperationsHeader, OperationsEntry, Contract, Account, ContractAccount, ContractSeries
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max, Q
from django.http import JsonResponse

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
        messages.warning(request, 'You have reached the maximum of 3 drafts this month. Continue a previous draft or delete one to start fresh.')
        return redirect('my_drafts')

    header = MainHeader.objects.create(employeeid=request.user)
    return redirect('add_entry', pk=header.mainheaderid)


@login_required(login_url='login')
def delete_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid=request.user, overallstatus='Draft')
        header.delete()
    return redirect('my_drafts')


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



@login_required(login_url='login')
def new_ops_sheet(request):
    if request.user.access_level != 5:
        return redirect('profile')
    
    crews = Crews.objects.filter(isactive=1)

    if request.method == 'POST':
        shiftdate = request.POST.get('shiftdate')
        shifttype = request.POST.get('shifttype')
        crewid = request.POST.get('crewid')

         #If a header already exists for this shifter + date + shift, redirect to it
        existing = OperationsHeader.objects.filter(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype
        ).first()
        if existing:
            return redirect('ops_sheet', pk=existing.opsheaderid)

        header = OperationsHeader.objects.create(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype,
            crewid_id=crewid
        )
        return redirect('ops_sheet', pk=header.opsheaderid)

    return render(request, 'timesheets/ops_sheet.html', {'header': None, 'crews': crews})


@login_required(login_url='login')
def ops_sheet(request, pk):
    if request.user.access_level != 5:
        return redirect('profile')

    header = get_object_or_404(OperationsHeader, opsheaderid=pk, shifterid=request.user)

    if header.overallstatus == 'Draft':
        hours_elapsed = (timezone.now() - header.startedat).total_seconds() / 3600
        if hours_elapsed > 72:
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            OperationsEntry.objects.filter(opsheaderid=header).update(linestatus='New')
            messages.warning(request, 'Your operations sheet was automatically submitted after 72 hours of inactivity.')

    hours_remaining = max(0, 72 - (timezone.now() - header.startedat).total_seconds() / 3600)

    if request.method == 'POST' and header.overallstatus == 'Draft':
        action = request.POST.get('action')

        if action == 'add_row':
            workcategoryid = request.POST.get('workcategoryid') or None

            OperationsEntry.objects.create(
                opsheaderid=header,
                employeeid_id=request.POST.get('employeeid'),
                contractid_id=request.POST.get('contractid'),
                accountid_id=request.POST.get('accountid') or None,
                workcategoryid_id=workcategoryid,
                hoursworked=request.POST.get('hoursworked'),
                remarks=request.POST.get('remarks') or None,
                hauledto=request.POST.get('hauledto') or None,
                tonnesorehauled=request.POST.get('tonnesorehauled') or None,
                tonneswastehauled=request.POST.get('tonneswastehauled') or None,
                lowgradehauled=request.POST.get('lowgradehauled') or None,
                tonnesoreskipped=request.POST.get('tonnesoreskipped') or None,
                tonneswasteskipped=request.POST.get('tonneswasteskipped') or None,
                lowgradeskipped=request.POST.get('lowgradeskipped') or None,
                longholefootage=request.POST.get('longholefootage') or None,
            )

        elif action == 'delete_row':
            entry_id = request.POST.get('entryid')
            OperationsEntry.objects.filter(opsentryid=entry_id, opsheaderid=header).delete()

        elif action == 'submit_sheet':
            if not OperationsEntry.objects.filter(opsheaderid=header).exists():
                return redirect('ops_sheet', pk=header.opsheaderid)
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            OperationsEntry.objects.filter(opsheaderid=header).update(linestatus='New')
            return redirect('my_ops_sheets')

        return redirect('ops_sheet', pk=header.opsheaderid)

    entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
        'employeeid', 'contractid', 'accountid', 'workcategoryid'
    )

    active_assignments = CrewAssignment.objects.filter(
        shifter=request.user, enddate__isnull=True
    ).select_related('employee')

    guest_employees = User.objects.filter(roleid__accessid__accessid=8, isactive=True)

    contracts = Contract.objects.filter(isactive=1)
    workcategories = Workcategory.objects.filter(isactive=1)

    prefill = {}
    for assignment in active_assignments:
        last = OperationsEntry.objects.filter(
            employeeid=assignment.employee
        ).order_by('-opsentryid').first()
        if last:
            prefill[assignment.employee.employeeid] = {
                'contractid': last.contractid_id,
                'accountid': last.accountid_id,
            }

    return render(request, 'timesheets/ops_sheet.html', {
        'header': header,
        'entries': entries,
        'active_assignments': active_assignments,
        'guest_employees': guest_employees,
        'contracts': contracts,
        'workcategories': workcategories,
        'prefill': prefill,
        'hours_remaining': round(hours_remaining, 1),
    })


@login_required(login_url='login')
def delete_ops_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(OperationsHeader, opsheaderid=pk, shifterid=request.user, overallstatus='Draft')
        header.delete()
    return redirect('my_ops_sheets')


def my_ops_sheets(request):
    if request.user.access_level != 5:
        return redirect('profile')

    sheets = OperationsHeader.objects.filter(shifterid=request.user).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked')
    ).order_by('-shiftdate', 'shifttype')

    return render(request, 'timesheets/my_ops_sheets.html', {'sheets': sheets})


@login_required(login_url='login')
def contract_account_management(request):
    if request.user.access_level != 2:
        return redirect('profile')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            contract_id = request.POST.get('contractid')
            account_id = request.POST.get('accountid')
            if contract_id and account_id:
                ContractAccount.objects.get_or_create(
                    contractid_id=contract_id,
                    accountid_id=account_id
                )

        elif action == 'remove':
            link_id = request.POST.get('contractaccountid')
            ContractAccount.objects.filter(contractaccountid=link_id).delete()

        return redirect('contract_account_management')

    series_list = ContractSeries.objects.prefetch_related(
        'contracts__contractaccount_set__accountid'
    ).filter(contracts__isactive=1).distinct()

    unassigned = Contract.objects.filter(isactive=1).exclude(series__isnull=False).prefetch_related('contractaccount_set__accountid')
    all_accounts = Account.objects.filter(isactive=1)

    return render(request, 'timesheets/contract_account_management.html', {
        'series_list': series_list,
        'unassigned': unassigned,
        'all_accounts': all_accounts,
    })


@login_required(login_url='login')
def accounts_for_contract(request):
    contract_id = request.GET.get('contract')
    if not contract_id:
        return JsonResponse([], safe=False)
    accounts = Account.objects.filter(
        contractaccount__contractid=contract_id,
        isactive=1
    ).values('accountid', 'accountcode', 'accounttitle')
    return JsonResponse(list(accounts), safe=False)
