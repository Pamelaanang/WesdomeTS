from datetime import date
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from users.models import User, Department, CrewAssignment, CrewCoverage
from .models import MainHeader, MainEntry, Crews, Workcategory, LeaveType, OperationsHeader, OperationsEntry, Contract, Account, ContractAccount, ContractSeries, OperationsBonus, BONUS_RATE_CODES, StatHoliday, BusinessHeader, BusinessEntry, Businesscategory, MONTH_CHOICES
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max, Q, Case, When, IntegerField
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from collections import defaultdict


def _stat_info():
    """Return (stat_dates set, stat_labels dict {date: label string})."""
    groups = defaultdict(list)
    for sh in StatHoliday.objects.filter(isactive=1).order_by('statdate', 'province'):
        groups[sh.statdate].append(f"{sh.statname} ({sh.province})")
    stat_labels = {d: ' / '.join(labels) for d, labels in groups.items()}
    return set(stat_labels.keys()), stat_labels


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

    if header.overallstatus not in ('Draft', 'Revision Required'):
        return redirect('profile')

    revision_mode = header.overallstatus == 'Revision Required'

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_entry':
            category_selection = request.POST.get('category_selection', '')
            workcategoryid = None
            leavetypeid = None
            if category_selection.startswith('wc_'):
                workcategoryid = category_selection[3:]
            elif category_selection.startswith('lt_'):
                leavetypeid = category_selection[3:]

            entryid = request.POST.get('entryid')
            if entryid:
                if revision_mode:
                    entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header, linestatus='Rejected')
                else:
                    entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                entry.workcategoryid_id = workcategoryid
                entry.leavetypeid_id = leavetypeid
                entry.sapworkid = request.POST.get('sapworkid') or None
                entry.shifttype = request.POST.get('shifttype')
                entry.hoursworked = request.POST.get('hoursworked')
                entry.startdate = request.POST.get('startdate')
                entry.entrydescription = request.POST.get('entrydescription') or None
                if revision_mode:
                    entry.linestatus = 'New'
                    entry.approvedat = None
                    entry.approvedby = None
                    entry.supervisornote = None
                entry.save()
            elif not revision_mode:
                MainEntry.objects.create(
                    mainheaderid=header,
                    workcategoryid_id=workcategoryid,
                    leavetypeid_id=leavetypeid,
                    sapworkid=request.POST.get('sapworkid') or None,
                    shifttype=request.POST.get('shifttype'),
                    hoursworked=request.POST.get('hoursworked'),
                    startdate=request.POST.get('startdate'),
                    entrydescription=request.POST.get('entrydescription') or None,
                )

        elif action == 'update_crew' and not revision_mode:
            header.crewid_id = request.POST.get('crewid') or None
            header.save()

        elif action == 'delete_entry':
            entry_id = request.POST.get('entryid')
            if revision_mode:
                MainEntry.objects.filter(mainentryid=entry_id, mainheaderid=header, linestatus='Rejected').delete()
            else:
                MainEntry.objects.filter(mainentryid=entry_id, mainheaderid=header).delete()

        elif action == 'submit_timesheet' and not revision_mode:
            if not MainEntry.objects.filter(mainheaderid=header).exists():
                return redirect('add_entry', pk=header.mainheaderid)
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            MainEntry.objects.filter(mainheaderid=header).update(linestatus='New')
            return redirect('profile')

        elif action == 'resubmit' and revision_mode:
            if not MainEntry.objects.filter(mainheaderid=header, linestatus='Rejected').exists():
                header.overallstatus = 'Submitted'
                header.submittedat = timezone.now()
                header.save()
                return redirect('my_drafts')

        return redirect('add_entry', pk=header.mainheaderid)

    entries = MainEntry.objects.filter(mainheaderid=header).select_related('workcategoryid', 'leavetypeid')
    workcategories = Workcategory.objects.all()
    leavetypes = LeaveType.objects.filter(isactive=1)
    hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    stat_dates, stat_labels = _stat_info()

    context = {
        'header': header,
        'entries': entries,
        'workcategories': workcategories,
        'leavetypes': leavetypes,
        'hours': hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'revision_mode': revision_mode,
    }
    if revision_mode:
        context['has_rejected'] = entries.filter(linestatus='Rejected').exists()
    else:
        context['crews'] = Crews.objects.all()
        context['today'] = timezone.now().date()
        context['days_remaining'] = 60 - (timezone.now() - header.startedat).days

    return render(request, 'timesheets/add_entry.html', context)

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

    if header.overallstatus in ('Completed', 'Revision Required'):
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
            if entries.filter(linestatus='Rejected').exists():
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.completedat = timezone.now()
            header.save()
            return redirect('approval_inbox')

        return redirect('review_timesheet', pk=header.mainheaderid)

    has_unreviewed = entries.filter(linestatus='New').exists()
    has_rejected = entries.filter(linestatus='Rejected').exists()
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/review_timesheet.html', {
        'header': header,
        'entries': entries,
        'empdate_submitted': empdate_submitted,
        'total_hours': total_hours,
        'hours_approved': hours_approved,
        'has_unreviewed': has_unreviewed,
        'has_rejected': has_rejected,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
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

    
    total_unprocessed = sum(d.unpaid_count for d in departments)
    return render(request, 'timesheets/payroll_unprocessed.html', {
        'departments': departments,
        'total_unprocessed': total_unprocessed,
    })


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

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_unprocessed_review.html', {
        'dept': dept,
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })



@login_required(login_url='login')
def payroll_processed(request):
    if request.user.access_level != 7:
        return redirect('profile')

    current_year = timezone.now().year
    departments = Department.objects.filter(isactive=1).annotate(
        employee_count=Count(
            'roles__user',
            filter=Q(
                roles__user__isactive=True,
                roles__user__mainheader__paidat__isnull=False,
                roles__user__mainheader__paidat__year=current_year,
            ),
            distinct=True,
        )
    )

    return render(request, 'timesheets/payroll_processed.html', {
        'departments': departments,
    })


@login_required(login_url='login')
def payroll_processed_dept(request, dept_id):
    if request.user.access_level != 7:
        return redirect('profile')

    dept = get_object_or_404(Department, departmentid=dept_id)
    current_year = timezone.now().year

    employees = User.objects.filter(
        roleid__departmentid=dept_id,
        isactive=True,
        mainheader__paidat__isnull=False,
        mainheader__paidat__year=current_year,
    ).distinct().annotate(
        paid_count=Count(
            'mainheader',
            filter=Q(mainheader__paidat__isnull=False, mainheader__paidat__year=current_year),
            distinct=True,
        ),
        total_hours=Sum(
            'mainheader__mainentry__hoursworked',
            filter=Q(
                mainheader__paidat__isnull=False,
                mainheader__paidat__year=current_year,
                mainheader__mainentry__linestatus='Approved',
            ),
        ),
    ).select_related('roleid').order_by('lastname', 'firstname')

    return render(request, 'timesheets/payroll_processed_dept.html', {
        'dept': dept,
        'employees': employees,
        'current_year': current_year,
    })


@login_required(login_url='login')
def payroll_processed_employee(request, employee_id):
    if request.user.access_level != 7:
        return redirect('profile')

    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    current_year = timezone.now().year
    selected_year = int(request.GET.get('year', current_year))

    processed_timesheets = MainHeader.objects.filter(
        employeeid=employee,
        paidat__isnull=False,
        paidat__year=selected_year,
    ).annotate(
        entry_count=Count('mainentry', filter=Q(mainentry__linestatus='Approved')),
        total_hours=Sum('mainentry__hoursworked', filter=Q(mainentry__linestatus='Approved')),
        date_from=Min('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
        date_to=Max('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
    ).filter(entry_count__gt=0).order_by('date_from')

    archive_years = [
        d.year for d in MainHeader.objects.filter(
            employeeid=employee,
            paidat__isnull=False,
        ).dates('paidat', 'year')
        if d.year != current_year
    ]

    return render(request, 'timesheets/payroll_processed_employee.html', {
        'employee': employee,
        'processed_timesheets': processed_timesheets,
        'current_year': current_year,
        'selected_year': selected_year,
        'archive_years': archive_years,
    })


@login_required(login_url='login')
def payroll_ops_unprocessed(request):
    if request.user.access_level != 7:
        return redirect('profile')

    opsheader = OperationsHeader.objects.filter(
        overallstatus='Completed',
        operationsentry__linestatus='Approved',
        operationsentry__paidat__isnull=True
    ).distinct().annotate(
        unpaidcount=Count('operationsentry', filter=Q(
        operationsentry__linestatus='Approved',
        operationsentry__paidat__isnull=True), distinct=True)
    ).select_related(
        'shifterid', 'crewid', 'coverageid'
    ).order_by(
        'shiftdate'
    )

    return render(request, 'timesheets/payroll_ops_unprocessed.html', {'opsheader': opsheader})


@login_required(login_url='login')
def payroll_ops_daily(request):
    if request.user.access_level != 7:
        return redirect('profile')

    current_year = timezone.now().year
    selected_year = int(request.GET.get('year', current_year))

    unpaid_header_ids = OperationsEntry.objects.filter(
        linestatus='Approved',
        paidat__isnull=True,
    ).values_list('opsheaderid', flat=True)

    months = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=selected_year,
    ).exclude(
        opsheaderid__in=unpaid_header_ids
    ).annotate(
        month=TruncMonth('shiftdate')
    ).values('month').annotate(
        sheet_count=Count('opsheaderid')
    ).order_by('-month')

    archive_years = [
        d.year for d in OperationsHeader.objects.filter(
            overallstatus='Completed',
        ).exclude(
            opsheaderid__in=unpaid_header_ids
        ).dates('shiftdate', 'year')
        if d.year != current_year
    ]

    return render(request, 'timesheets/payroll_ops_daily.html', {
        'months': months,
        'current_year': current_year,
        'selected_year': selected_year,
        'archive_years': archive_years,
    })


@login_required(login_url='login')
def payroll_ops_daily_month(request, year, month):
    if request.user.access_level != 7:
        return redirect('profile')

    unpaid_header_ids = OperationsEntry.objects.filter(
        linestatus='Approved',
        paidat__isnull=True,
    ).values_list('opsheaderid', flat=True)

    sheets = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).exclude(
        opsheaderid__in=unpaid_header_ids
    ).select_related(
        'shifterid', 'crewid', 'coverageid'
    ).annotate(
        entry_count=Count('operationsentry', filter=Q(operationsentry__linestatus='Approved'))
    ).order_by('shiftdate', 'shifttype')

    return render(request, 'timesheets/payroll_ops_daily_month.html', {
        'sheets': sheets,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
    })


@login_required(login_url='login')
def payroll_ops_members(request):
    if request.user.access_level != 7:
        return redirect('profile')

    current_year = timezone.now().year

    members = User.objects.filter(
        operationsentry__linestatus='Approved',
        operationsentry__paidat__isnull=False,
        operationsentry__paidat__year=current_year,
    ).distinct().annotate(
        paid_entry_count=Count(
            'operationsentry',
            filter=Q(
                operationsentry__linestatus='Approved',
                operationsentry__paidat__isnull=False,
                operationsentry__paidat__year=current_year,
            ),
            distinct=True,
        )
    ).select_related('roleid').order_by('lastname', 'firstname')

    return render(request, 'timesheets/payroll_ops_members.html', {
        'members': members,
        'current_year': current_year,
    })


@login_required(login_url='login')
def payroll_ops_member_detail(request, employee_id):
    if request.user.access_level != 7:
        return redirect('profile')

    member = get_object_or_404(User, employeeid=employee_id)
    current_year = timezone.now().year
    selected_year = int(request.GET.get('year', current_year))

    months = OperationsEntry.objects.filter(
        employeeid=member,
        linestatus='Approved',
        paidat__isnull=False,
        paidat__year=selected_year,
    ).annotate(
        month=TruncMonth('paidat')
    ).values('month').annotate(
        entry_count=Count('opsentryid')
    ).order_by('-month')

    archive_years = [
        d.year for d in OperationsEntry.objects.filter(
            employeeid=member,
            linestatus='Approved',
            paidat__isnull=False,
        ).dates('paidat', 'year')
        if d.year != current_year
    ]

    return render(request, 'timesheets/payroll_ops_member_detail.html', {
        'member': member,
        'months': months,
        'current_year': current_year,
        'selected_year': selected_year,
        'archive_years': archive_years,
    })


@login_required(login_url='login')
def payroll_ops_member_month(request, employee_id, year, month):
    if request.user.access_level != 7:
        return redirect('profile')

    member = get_object_or_404(User, employeeid=employee_id)
    month_date = date(year, month, 1)

    if request.method == 'POST' and request.POST.get('action') == 'apply_bonus':
        bonus = get_object_or_404(OperationsBonus, employeeid=member, bonusmonth=month_date, status='Submitted')
        bonus.status = 'Applied'
        bonus.appliedbypayroll = request.user
        bonus.appliedatpayroll = timezone.now()
        bonus.save()
        return redirect('payroll_ops_member_month', employee_id=employee_id, year=year, month=month)

    entries = OperationsEntry.objects.filter(
        employeeid=member,
        linestatus='Approved',
        paidat__isnull=False,
        paidat__year=year,
        paidat__month=month,
    ).select_related(
        'opsheaderid__shifterid', 'opsheaderid__crewid', 'contractid', 'accountid', 'workcategoryid', 'paidby'
    ).order_by('opsheaderid__shiftdate', 'opsheaderid__shifttype')

    total_hours = entries.aggregate(total=Sum('hoursworked'))['total'] or 0
    bonus = OperationsBonus.objects.filter(employeeid=member, bonusmonth=month_date).first()

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_ops_member_month.html', {
        'member': member,
        'entries': entries,
        'total_hours': total_hours,
        'year': year,
        'month': month,
        'month_date': month_date,
        'bonus': bonus,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def superintendent_ops_members(request):
    if request.user.access_level != 2:
        return redirect('profile')
    members_qs = User.objects.filter(
        operationsentry__opsheaderid__overallstatus='Completed',
        operationsentry__linestatus='Approved',
    ).distinct().select_related('roleid').order_by('lastname', 'firstname')
    return render(request, 'timesheets/superintendent_ops_members.html', {
        'members': members_qs,
    })


@login_required(login_url='login')
def superintendent_ops_member_detail(request, employee_id):
    if request.user.access_level != 2:
        return redirect('profile')
    member = get_object_or_404(User, employeeid=employee_id)
    months_qs = OperationsEntry.objects.filter(
        employeeid=member,
        opsheaderid__overallstatus='Completed',
        linestatus='Approved',
    ).annotate(
        month=TruncMonth('opsheaderid__shiftdate')
    ).values('month').annotate(
        entry_count=Count('opsentryid')
    ).order_by('-month')

    bonuses = {
        (b.bonusmonth.year, b.bonusmonth.month): b
        for b in OperationsBonus.objects.filter(employeeid=member)
    }
    months = [
        {
            'month': m['month'],
            'entry_count': m['entry_count'],
            'bonus': bonuses.get((m['month'].year, m['month'].month)),
        }
        for m in months_qs
    ]
    return render(request, 'timesheets/superintendent_ops_member_detail.html', {
        'member': member,
        'months': months,
    })


@login_required(login_url='login')
def superintendent_ops_member_month(request, employee_id, year, month):
    if request.user.access_level != 2:
        return redirect('profile')
    member = get_object_or_404(User, employeeid=employee_id)
    month_date = date(year, month, 1)
    entries = OperationsEntry.objects.filter(
        employeeid=member,
        opsheaderid__overallstatus='Completed',
        linestatus='Approved',
        opsheaderid__shiftdate__year=year,
        opsheaderid__shiftdate__month=month,
    ).select_related(
        'opsheaderid__shifterid', 'opsheaderid__crewid',
        'contractid', 'accountid', 'workcategoryid',
    ).order_by('opsheaderid__shiftdate', 'opsheaderid__shifttype')
    total_hours = entries.aggregate(total=Sum('hoursworked'))['total'] or 0
    bonus = OperationsBonus.objects.filter(employeeid=member, bonusmonth=month_date).first()

    if request.method == 'POST':
        if bonus and bonus.status == 'Applied':
            return redirect('superintendent_ops_member_month', employee_id=employee_id, year=year, month=month)
        action = request.POST.get('action')
        ratecode = request.POST.get('bonusratecode', '').strip()
        notes = request.POST.get('notes', '').strip()
        if not bonus:
            bonus = OperationsBonus(employeeid=member, bonusmonth=month_date)
        bonus.bonusratecode = ratecode
        bonus.notes = notes or None
        if action == 'confirm':
            bonus.status = 'Submitted'
            bonus.reviewedby = request.user
            bonus.reviewedat = timezone.now()
        else:
            bonus.status = 'Draft'
            bonus.reviewedby = None
            bonus.reviewedat = None
        bonus.save()
        return redirect('superintendent_ops_member_month', employee_id=employee_id, year=year, month=month)

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/superintendent_ops_member_month.html', {
        'member': member,
        'entries': entries,
        'total_hours': total_hours,
        'year': year,
        'month': month,
        'month_date': month_date,
        'bonus': bonus,
        'rate_codes': BONUS_RATE_CODES,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def payroll_ops_sheet(request,pk):
    if request.user.access_level != 7:
        return redirect('profile')

    opsheader = get_object_or_404(
        OperationsHeader, opsheaderid=pk, overallstatus='Completed')

    opsentries = OperationsEntry.objects.filter(
        opsheaderid=opsheader, linestatus='Approved'
    ).select_related(
        'employeeid', 'contractid', 'accountid', 'workcategoryid', 'paidby'
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'mark_as_paid':
            opsentries.filter(paidat__isnull=True).update(paidat=timezone.now(), paidby=request.user)
            messages.success(request, f'Payment for operations sheet {opsheader.opsheaderid} marked as complete.')
            return redirect('payroll_ops_unprocessed')

    all_paid = not opsentries.filter(paidat__isnull=True).exists()
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_ops_sheet.html', {
        'opsheader': opsheader,
        'opsentries': opsentries,
        'all_paid': all_paid,
        'is_stat': opsheader.shiftdate in stat_dates,
        'stat_label': stat_labels.get(opsheader.shiftdate, ''),
    })



@login_required(login_url='login')
def my_drafts(request):
    drafts = MainHeader.objects.filter(employeeid=request.user, overallstatus__in=['Draft', 'Revision Required']).annotate(
        entry_count=Count('mainentry'),
        total_hours=Sum('mainentry__hoursworked'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate')
    ).order_by('-startedat')

    return render(request, 'timesheets/my_drafts.html', {'drafts': drafts})


@login_required(login_url='login')
def my_timesheets_approved(request):
    if request.user.access_level != 6:
        return redirect('profile')
    months = MainHeader.objects.filter(
        employeeid=request.user,
        overallstatus='Completed'
    ).annotate(
        month=TruncMonth('submittedat')
    ).values('month').annotate(
        sheet_count=Count('mainheaderid', distinct=True),
        total_hours=Sum('mainentry__hoursworked')
    ).order_by('-month')
    return render(request, 'timesheets/my_timesheets_approved.html', {'months': months})


@login_required(login_url='login')
def my_timesheets_approved_month(request, year, month):
    if request.user.access_level != 6:
        return redirect('profile')
    headers = MainHeader.objects.filter(
        employeeid=request.user,
        overallstatus='Completed',
        submittedat__year=year,
        submittedat__month=month,
    ).annotate(
        entry_count=Count('mainentry'),
        total_hours=Sum('mainentry__hoursworked'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate'),
    ).order_by('submittedat')
    return render(request, 'timesheets/my_timesheets_approved_month.html', {
        'headers': headers,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def my_timesheets_paid(request):
    if request.user.access_level != 6:
        return redirect('profile')
    months = MainHeader.objects.filter(
        employeeid=request.user,
        paidat__isnull=False,
    ).annotate(
        month=TruncMonth('paidat')
    ).values('month').annotate(
        sheet_count=Count('mainheaderid', distinct=True),
        total_hours=Sum('mainentry__hoursworked')
    ).order_by('-month')
    return render(request, 'timesheets/my_timesheets_paid.html', {'months': months})


@login_required(login_url='login')
def my_timesheets_paid_month(request, year, month):
    if request.user.access_level != 6:
        return redirect('profile')
    headers = MainHeader.objects.filter(
        employeeid=request.user,
        paidat__isnull=False,
        paidat__year=year,
        paidat__month=month,
    ).select_related('paidby').annotate(
        entry_count=Count('mainentry'),
        total_hours=Sum('mainentry__hoursworked'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate'),
    ).order_by('paidat')
    return render(request, 'timesheets/my_timesheets_paid_month.html', {
        'headers': headers,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def new_ops_sheet(request):
    if request.user.access_level != 5:
        return redirect('profile')

    today = timezone.now().date()
    crews = Crews.objects.filter(isactive=1)
    active_coverages = CrewCoverage.objects.filter(
        covering_shifter=request.user,
        startdate__lte=today,
    ).filter(
        Q(enddate__isnull=True) | Q(enddate__gte=today)
    ).select_related('home_shifter')

    if request.method == 'POST':
        shiftdate = request.POST.get('shiftdate')
        shifttype = request.POST.get('shifttype')
        crewid = request.POST.get('crewid')
        coverage_id = request.POST.get('coverage_id') or None

        try:
            from datetime import date as _date
            if shiftdate and _date.fromisoformat(shiftdate) > today:
                return render(request, 'timesheets/ops_sheet.html', {
                    'header': None,
                    'crews': crews,
                    'active_coverages': active_coverages,
                    'own_shiftertype': request.user.shiftertype or '',
                    'coverage_sections': {},
                    'error': 'Crew sheets cannot be created for future dates.',
                })
        except ValueError:
            pass

        existing = OperationsHeader.objects.filter(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype,
            coverageid_id=coverage_id,
        ).first()
        if existing:
            return redirect('ops_sheet', pk=existing.opsheaderid)

        # Derive section: own crew → own shiftertype; coverage → home shifter's shiftertype
        section = None
        if coverage_id:
            cov = active_coverages.filter(coverageid=coverage_id).first()
            if cov:
                section = cov.home_shifter.shiftertype
        else:
            section = request.user.shiftertype

        header = OperationsHeader.objects.create(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype,
            crewid_id=crewid,
            coverageid_id=coverage_id,
            section=section,
        )
        return redirect('ops_sheet', pk=header.opsheaderid)

    # Build coverage_sections map for JS: { coverageid: home_shifter.shiftertype }
    coverage_sections = {
        str(cov.coverageid): cov.home_shifter.shiftertype or ''
        for cov in active_coverages
    }

    return render(request, 'timesheets/ops_sheet.html', {
        'header': None,
        'crews': crews,
        'active_coverages': active_coverages,
        'own_shiftertype': request.user.shiftertype or '',
        'coverage_sections': coverage_sections,
    })


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

    if request.method == 'POST' and header.overallstatus in ('Draft', 'Revision Required'):
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
                linestatus='New' if header.overallstatus == 'Revision Required' else 'Draft',
            )

        elif action == 'delete_row':
            entry_id = request.POST.get('entryid')
            qs = OperationsEntry.objects.filter(opsentryid=entry_id, opsheaderid=header)
            if header.overallstatus == 'Revision Required':
                qs = qs.filter(linestatus='Rejected')
            qs.delete()

        elif action == 'submit_sheet' and header.overallstatus == 'Draft':
            if not OperationsEntry.objects.filter(opsheaderid=header).exists():
                return redirect('ops_sheet', pk=header.opsheaderid)
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            OperationsEntry.objects.filter(opsheaderid=header).update(linestatus='New')
            return redirect('my_ops_sheets')

        elif action == 'edit_row' and header.overallstatus in ('Draft', 'Revision Required'):
            if header.overallstatus == 'Revision Required':
                entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header, linestatus='Rejected')
            else:
                entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header)
            entry.contractid_id = request.POST.get('contractid')
            entry.accountid_id = request.POST.get('accountid') or None
            entry.workcategoryid_id = request.POST.get('workcategoryid') or None
            entry.hoursworked = request.POST.get('hoursworked')
            entry.remarks = request.POST.get('remarks') or None
            entry.hauledto = request.POST.get('hauledto') or None
            entry.tonnesorehauled = request.POST.get('tonnesorehauled') or None
            entry.tonneswastehauled = request.POST.get('tonneswastehauled') or None
            entry.lowgradehauled = request.POST.get('lowgradehauled') or None
            entry.tonnesoreskipped = request.POST.get('tonnesoreskipped') or None
            entry.tonneswasteskipped = request.POST.get('tonneswasteskipped') or None
            entry.lowgradeskipped = request.POST.get('lowgradeskipped') or None
            entry.longholefootage = request.POST.get('longholefootage') or None
            if header.overallstatus == 'Revision Required':
                entry.linestatus = 'New'
                entry.captainnote = None
                entry.approvedby_capt = None
                entry.approvedat_capt = None
            entry.save()

        elif action == 'resubmit' and header.overallstatus == 'Revision Required':
            OperationsEntry.objects.filter(opsheaderid=header).exclude(linestatus='Approved').update(linestatus='New')
            header.overallstatus = 'Submitted'
            header.save()
            return redirect('my_ops_sheets')

        return redirect('ops_sheet', pk=header.opsheaderid)

    entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
        'employeeid', 'contractid', 'accountid', 'workcategoryid', 'approvedby_capt'
    )

    coverage = header.coverageid
    effective_shifter = coverage.home_shifter if coverage else request.user

    active_assignments = CrewAssignment.objects.filter(
        shifter=effective_shifter, enddate__isnull=True
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

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/ops_sheet.html', {
        'header': header,
        'entries': entries,
        'active_assignments': active_assignments,
        'guest_employees': guest_employees,
        'contracts': contracts,
        'workcategories': workcategories,
        'prefill': prefill,
        'hours_remaining': round(hours_remaining, 1),
        'coverage': coverage,
        'is_stat': header.shiftdate in stat_dates,
        'stat_label': stat_labels.get(header.shiftdate, ''),
    })


@login_required(login_url='login')
def my_ops_approvals(request):
    if request.user.access_level != 5:
        return redirect('profile')
    months = OperationsHeader.objects.filter(
        shifterid=request.user,
        overallstatus='Completed'
    ).annotate(
        month=TruncMonth('shiftdate')
    ).values('month').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
        total_hours=Sum('operationsentry__hoursworked')
    ).order_by('-month')
    return render(request, 'timesheets/my_ops_approvals.html', {'months': months})


@login_required(login_url='login')
def my_ops_approvals_month(request, year, month):
    if request.user.access_level != 5:
        return redirect('profile')
    sheets = OperationsHeader.objects.filter(
        shifterid=request.user,
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).select_related(
        'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked')
    ).order_by('shiftdate', 'shifttype')
    return render(request, 'timesheets/my_ops_approvals_month.html', {
        'sheets': sheets,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def my_ops_completed(request):
    if request.user.access_level != 4:
        return redirect('profile')
    months = OperationsHeader.objects.filter(
        ohapprovedby_capt=request.user,
        overallstatus='Completed'
    ).annotate(
        month=TruncMonth('shiftdate')
    ).values('month').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
        total_hours=Sum('operationsentry__hoursworked')
    ).order_by('-month')
    return render(request, 'timesheets/my_ops_completed.html', {'months': months})


@login_required(login_url='login')
def my_ops_completed_month(request, year, month):
    if request.user.access_level != 4:
        return redirect('profile')
    sheets = OperationsHeader.objects.filter(
        ohapprovedby_capt=request.user,
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked')
    ).order_by('shiftdate', 'shifttype')
    return render(request, 'timesheets/my_ops_completed_month.html', {
        'sheets': sheets,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def delete_ops_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(OperationsHeader, opsheaderid=pk, shifterid=request.user, overallstatus='Draft')
        header.delete()
    return redirect('my_ops_sheets')


@login_required(login_url='login')
def my_ops_sheets(request):
    if request.user.access_level != 5:
        return redirect('profile')

    sheets = OperationsHeader.objects.filter(
        shifterid=request.user
    ).exclude(
        overallstatus='Completed'
    ).select_related(
        'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked'),
        status_order=Case(
            When(overallstatus='Draft', then=0),
            When(overallstatus='Revision Required', then=1),
            When(overallstatus='Submitted', then=2),
            When(overallstatus='In Progress', then=3),
            default=4,
            output_field=IntegerField(),
        ),
    ).order_by('status_order', '-shiftdate', 'shifttype')

    return render(request, 'timesheets/my_ops_sheets.html', {'sheets': sheets})

@login_required(login_url='login')
def ops_approval_inbox(request):
    if request.user.access_level != 4:
        return redirect('profile')

    action_needed = OperationsHeader.objects.filter(
        overallstatus='Submitted',
    ).filter(
        Q(ohapprovedby_capt__isnull=True) | Q(ohapprovedby_capt=request.user)
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked'),
    ).order_by('shiftdate', 'shifttype')

    in_progress_sheets = OperationsHeader.objects.filter(
        overallstatus='In Progress', ohapprovedby_capt=request.user
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter'
    ).annotate(
        entry_count=Count('operationsentry'),
        total_hours=Sum('operationsentry__hoursworked'),
        approved_count=Count('operationsentry', filter=Q(operationsentry__linestatus='Approved')),
        new_count=Count('operationsentry', filter=Q(operationsentry__linestatus='New')),
    ).order_by('shiftdate', 'shifttype')

    pending_revision_sheets = OperationsHeader.objects.filter(
        overallstatus='Revision Required', ohapprovedby_capt=request.user
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter'
    ).annotate(
        entry_count=Count('operationsentry'),
        rejected_count=Count('operationsentry', filter=Q(operationsentry__linestatus='Rejected')),
    ).order_by('shiftdate', 'shifttype')

    return render(request, 'timesheets/ops_approval_inbox.html', {
        'action_needed': action_needed,
        'in_progress_sheets': in_progress_sheets,
        'pending_revision_sheets': pending_revision_sheets,
    })


@login_required(login_url='login')
def review_ops_sheet(request,pk):
    if request.user.access_level != 4:
        return redirect('profile')

    header = get_object_or_404(
        OperationsHeader,
        opsheaderid=pk,
        overallstatus__in=['Submitted', 'In Progress', 'Completed'],
    )

    if header.ohapprovedby_capt and header.ohapprovedby_capt != request.user:
        return redirect('ops_approval_inbox')

    readonly = header.overallstatus == 'Completed'

    if request.method == 'POST' and not readonly:
        action = request.POST.get('action')

        if action in ('approve', 'reject'):
            entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header)

            if action == 'approve':
                entry.linestatus = 'Approved'
                entry.approvedby_capt = request.user
                entry.approvedat_capt = timezone.now()
                entry.captainnote = None
                entry.save()

            elif action == 'reject':
                note = request.POST.get('captainnote', '').strip()
                if not note:
                    return redirect('review_ops_sheet', pk=pk)
                entry.captainnote = note
                entry.linestatus = 'Rejected'
                entry.approvedby_capt = request.user
                entry.approvedat_capt = timezone.now()
                entry.save()

            if not header.ohapprovedby_capt:
                header.ohapprovedby_capt = request.user
                header.overallstatus = 'In Progress'
                header.save()
            elif header.overallstatus == 'Submitted':
                header.overallstatus = 'In Progress'
                header.save()
            return redirect('review_ops_sheet', pk=pk)

        elif action == 'finish_review':
            all_entries = OperationsEntry.objects.filter(opsheaderid=header)
            if all_entries.filter(linestatus='New').exists():
                return redirect('review_ops_sheet', pk=pk)
            if all_entries.filter(linestatus='Rejected').exists():
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.ohapprovedat_capt = timezone.now()  
            header.save()
            return redirect('ops_approval_inbox') 

    entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
        'employeeid', 'contractid', 'accountid', 'workcategoryid', 'approvedby_capt'
        )
    has_unreviewed = entries.filter(linestatus='New').exists()
    has_rejected = entries.filter(linestatus='Rejected').exists()

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/review_ops_sheet.html', {
        'header': header,
        'entries': entries,
        'has_unreviewed': has_unreviewed,
        'has_rejected': has_rejected,
        'readonly': readonly,
        'is_stat': header.shiftdate in stat_dates,
        'stat_label': stat_labels.get(header.shiftdate, ''),
    })







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

        series_id = request.POST.get('series_id', '')
        base_url = reverse('contract_account_management')
        return redirect(f'{base_url}?open={series_id}' if series_id else base_url)

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


# ─── Business Timesheet Flow (al=3,4,5) ───────────────────────────────────────

_BUSINESS_SUBMITTERS = [3, 4, 5]
_BUSINESS_REVIEWERS = [2, 3, 4]
_MONTH_NAMES = dict(MONTH_CHOICES)


@login_required(login_url='login')
def new_business_timesheet(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    now = timezone.now()

    if request.method == 'POST':
        try:
            month = int(request.POST.get('month', 0))
            year = int(request.POST.get('year', 0))
        except (ValueError, TypeError):
            month, year = 0, 0

        if not (1 <= month <= 12) or year < 2020:
            messages.error(request, 'Please select a valid month and year.')
            return redirect('new_business_timesheet')

        existing = BusinessHeader.objects.filter(
            employeeid=request.user,
            periodmonth=month,
            periodyear=year,
        ).first()

        if existing:
            if existing.overallstatus == 'Draft':
                return redirect('add_business_entry', pk=existing.businessheaderid)
            messages.warning(request, f'A timesheet for {_MONTH_NAMES[month]} {year} already exists ({existing.overallstatus}).')
            return redirect('my_business_drafts')

        header = BusinessHeader.objects.create(
            employeeid=request.user,
            periodmonth=month,
            periodyear=year,
        )
        return redirect('add_business_entry', pk=header.businessheaderid)

    current_year = now.year
    return render(request, 'timesheets/business_new.html', {
        'month_choices': MONTH_CHOICES,
        'year_choices': [current_year - 1, current_year, current_year + 1],
        'default_month': now.month,
        'default_year': current_year,
    })


@login_required(login_url='login')
def add_business_entry(request, pk):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    header = get_object_or_404(BusinessHeader, businessheaderid=pk, employeeid=request.user)

    if header.overallstatus == 'Revision Required':
        if request.method == 'POST':
            action = request.POST.get('action')

            if action == 'save_entry':
                sel = request.POST.get('category_selection', '')
                bcat_id = sel[3:] if sel.startswith('bc_') else None
                lt_id = sel[3:] if sel.startswith('lt_') else None
                entryid = request.POST.get('entryid')
                if entryid:
                    entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header, linestatus='Rejected')
                    entry.businesscategoryid_id = bcat_id
                    entry.leavetypeid_id = lt_id
                    entry.dateworked = request.POST.get('dateworked')
                    entry.shifttype = request.POST.get('shifttype') or None
                    entry.hoursworked = request.POST.get('hoursworked')
                    entry.entrydescription = request.POST.get('entrydescription') or None
                    entry.linestatus = 'New'
                    entry.approvedat = None
                    entry.approvedby = None
                    entry.supervisornote = None
                    entry.save()

            elif action == 'delete_entry':
                BusinessEntry.objects.filter(
                    businessentryid=request.POST.get('entryid'),
                    businessheaderid=header,
                    linestatus='Rejected',
                ).delete()

            elif action == 'resubmit':
                if not BusinessEntry.objects.filter(businessheaderid=header, linestatus='Rejected').exists():
                    header.overallstatus = 'Submitted'
                    header.submittedat = timezone.now()
                    header.save()
                    return redirect('my_business_drafts')

            return redirect('add_business_entry', pk=header.businessheaderid)

        entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
            'businesscategoryid', 'leavetypeid'
        ).order_by('dateworked')
        total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
        stat_dates, stat_labels = _stat_info()
        return render(request, 'timesheets/add_business_entry.html', {
            'header': header,
            'entries': entries,
            'business_categories': Businesscategory.objects.filter(isactive=1),
            'leavetypes': LeaveType.objects.filter(isactive=1),
            'total_hours': total_hours,
            'stat_dates': stat_dates,
            'stat_labels': stat_labels,
            'revision_mode': True,
            'has_rejected': entries.filter(linestatus='Rejected').exists(),
        })

    if header.overallstatus != 'Draft':
        entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
            'businesscategoryid', 'leavetypeid'
        ).order_by('dateworked')
        total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
        stat_dates, stat_labels = _stat_info()
        return render(request, 'timesheets/add_business_entry.html', {
            'header': header,
            'entries': entries,
            'total_hours': total_hours,
            'stat_dates': stat_dates,
            'stat_labels': stat_labels,
            'readonly': True,
        })

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_entry':
            sel = request.POST.get('category_selection', '')
            bcat_id = sel[3:] if sel.startswith('bc_') else None
            lt_id = sel[3:] if sel.startswith('lt_') else None

            entryid = request.POST.get('entryid')
            if entryid:
                entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header)
                entry.businesscategoryid_id = bcat_id
                entry.leavetypeid_id = lt_id
                entry.dateworked = request.POST.get('dateworked')
                entry.shifttype = request.POST.get('shifttype') or 'Day'
                entry.hoursworked = request.POST.get('hoursworked')
                entry.entrydescription = request.POST.get('entrydescription') or None
                entry.save()
            else:
                BusinessEntry.objects.create(
                    businessheaderid=header,
                    businesscategoryid_id=bcat_id,
                    leavetypeid_id=lt_id,
                    dateworked=request.POST.get('dateworked'),
                    shifttype=request.POST.get('shifttype') or 'Day',
                    hoursworked=request.POST.get('hoursworked'),
                    entrydescription=request.POST.get('entrydescription') or None,
                )

        elif action == 'delete_entry':
            BusinessEntry.objects.filter(
                businessentryid=request.POST.get('entryid'),
                businessheaderid=header,
            ).delete()

        elif action == 'submit_timesheet':
            if not BusinessEntry.objects.filter(businessheaderid=header).exists():
                return redirect('add_business_entry', pk=header.businessheaderid)
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            BusinessEntry.objects.filter(businessheaderid=header).update(linestatus='New')
            return redirect('my_business_drafts')

        return redirect('add_business_entry', pk=header.businessheaderid)

    entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
        'businesscategoryid', 'leavetypeid'
    ).order_by('dateworked')
    total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/add_business_entry.html', {
        'header': header,
        'entries': entries,
        'business_categories': Businesscategory.objects.filter(isactive=1),
        'leavetypes': LeaveType.objects.filter(isactive=1),
        'total_hours': total_hours,
        'today': timezone.now().date(),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def delete_business_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(BusinessHeader, businessheaderid=pk, employeeid=request.user, overallstatus='Draft')
        header.delete()
    return redirect('my_business_drafts')


@login_required(login_url='login')
def my_business_drafts(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    drafts = BusinessHeader.objects.filter(
        employeeid=request.user,
        overallstatus__in=['Draft', 'Submitted', 'In Progress', 'Revision Required'],
    ).annotate(
        entry_count=Count('businessentry'),
        total_hours=Sum('businessentry__hoursworked'),
    ).order_by('-periodyear', '-periodmonth')

    return render(request, 'timesheets/my_business_drafts.html', {
        'drafts': drafts,
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def my_business_approved(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    periods = BusinessHeader.objects.filter(
        employeeid=request.user,
        overallstatus='Completed',
    ).values('periodyear', 'periodmonth').annotate(
        sheet_count=Count('businessheaderid'),
        total_hours=Sum('businessentry__hoursworked'),
    ).order_by('-periodyear', '-periodmonth')

    return render(request, 'timesheets/my_business_approved.html', {
        'periods': periods,
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def my_business_approved_month(request, year, month):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    headers = BusinessHeader.objects.filter(
        employeeid=request.user,
        overallstatus='Completed',
        periodyear=year,
        periodmonth=month,
    )
    entries = BusinessEntry.objects.filter(
        businessheaderid__in=headers,
    ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')
    total_hours = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/my_business_approved_month.html', {
        'year': year,
        'month': month,
        'month_name': _MONTH_NAMES.get(month, ''),
        'entries': entries,
        'total_hours': total_hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def my_business_paid(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    periods = BusinessHeader.objects.filter(
        employeeid=request.user,
        paidat__isnull=False,
    ).values('periodyear', 'periodmonth').annotate(
        sheet_count=Count('businessheaderid'),
        total_hours=Sum('businessentry__hoursworked'),
    ).order_by('-periodyear', '-periodmonth')

    return render(request, 'timesheets/my_business_paid.html', {
        'periods': periods,
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def my_business_paid_month(request, year, month):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    headers = BusinessHeader.objects.filter(
        employeeid=request.user,
        paidat__isnull=False,
        periodyear=year,
        periodmonth=month,
    )
    entries = BusinessEntry.objects.filter(
        businessheaderid__in=headers,
    ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')
    total_hours = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    paid_at = headers.first().paidat if headers.exists() else None
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/my_business_paid_month.html', {
        'year': year,
        'month': month,
        'month_name': _MONTH_NAMES.get(month, ''),
        'entries': entries,
        'total_hours': total_hours,
        'paid_at': paid_at,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def business_approval_inbox(request):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')

    subordinates = User.objects.filter(supervisorid=request.user)
    pending = BusinessHeader.objects.filter(
        employeeid__in=subordinates,
        overallstatus__in=['Submitted', 'In Progress'],
    ).select_related('employeeid__roleid').annotate(
        entry_count=Count('businessentry'),
    ).order_by('employeeid__lastname', 'employeeid__firstname', '-submittedat')

    return render(request, 'timesheets/business_approval_inbox.html', {
        'pending': pending,
        'cards_waiting': pending.count(),
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def review_business_timesheet(request, pk):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')

    subordinates = User.objects.filter(supervisorid=request.user)
    header = get_object_or_404(BusinessHeader, businessheaderid=pk, employeeid__in=subordinates)

    if header.overallstatus in ('Completed', 'Revision Required'):
        return redirect('business_approval_inbox')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in ('approve', 'reject'):
            entryid = request.POST.get('entryid')
            if entryid:
                entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header)
                entry.linestatus = 'Approved' if action == 'approve' else 'Rejected'
                entry.approvedat = timezone.now()
                entry.supervisornote = request.POST.get('supervisornote') or None
                entry.approvedby = request.user
                entry.save()
                header.overallstatus = 'In Progress'
                header.save()

        elif action == 'finish_review':
            has_rejected_now = BusinessEntry.objects.filter(businessheaderid=header, linestatus='Rejected').exists()
            if has_rejected_now:
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.completedat = timezone.now()
            header.save()
            return redirect('business_approval_inbox')

        return redirect('review_business_timesheet', pk=header.businessheaderid)

    entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
        'businesscategoryid', 'leavetypeid', 'approvedby'
    ).order_by('dateworked')
    total_hours = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    hours_approved = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    has_unreviewed = entries.filter(linestatus='New').exists()
    has_rejected = entries.filter(linestatus='Rejected').exists()
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/review_business_timesheet.html', {
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'hours_approved': hours_approved,
        'has_unreviewed': has_unreviewed,
        'has_rejected': has_rejected,
        'month_names': _MONTH_NAMES,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })
