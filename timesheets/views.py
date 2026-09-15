from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from users.models import User, Department, CrewAssignment, CrewCoverage
from .models import MainHeader, MainEntry, Crews, Workcategory, Opscategory, LeaveType, OperationsHeader, OperationsEntry, Contract, Account, ContractAccount, ContractSeries, MinerLevel, OperationsBonus, BONUS_RATE_CODES, StatHoliday, BusinessHeader, BusinessEntry, Businesscategory, MONTH_CHOICES, EmployeeBonus, BONUS_TYPE_CHOICES, Auditlog, submission_deadline
from django.utils import timezone
from django.db.models import Sum, Count, Min, Max, Q, Case, When, IntegerField, Prefetch
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.core.paginator import Paginator
from collections import defaultdict
from .audit import log_action
from . import leave as leave_rules
from django.core.management import call_command
from io import StringIO


def _validate_leave_entry(user, leavetypeid, startdate_str, hoursworked_str, exclude_entry=None):
    """Shared save-time leave validation for the Maintenance/Business/Operations
    add-entry paths. Returns an error string to block the save, or None."""
    if not (leavetypeid and startdate_str and hoursworked_str):
        return None
    leave_type_obj = LeaveType.objects.filter(pk=leavetypeid).first()
    if not leave_type_obj:
        return None
    try:
        entry_year = date.fromisoformat(startdate_str).year
        hours = Decimal(hoursworked_str)
    except (ValueError, InvalidOperation):
        return None
    if leave_type_obj.leavetypename == leave_rules.VACATION_TYPE_NAME:
        return leave_rules.validate_vacation_entry(user, entry_year, hours, exclude_entry=exclude_entry)
    if leave_type_obj.leavetypename == leave_rules.FLOATER_TYPE_NAME:
        return leave_rules.validate_floater_entry(user, entry_year, exclude_entry=exclude_entry)
    return None


def _stat_info():
    """Return (stat_dates set, stat_labels dict {date: label string})."""
    groups = defaultdict(list)
    for sh in StatHoliday.objects.filter(isactive=1).order_by('statdate', 'province'):
        groups[sh.statdate].append(f"{sh.statname} ({sh.province})")
    stat_labels = {d: ' / '.join(labels) for d, labels in groups.items()}
    return set(stat_labels.keys()), stat_labels


def _payable_hours_split(entries, category_field):
    """Given an entries queryset and its category FK field name (e.g. 'workcategoryid',
    'businesscategoryid', 'opscategoryid'), return (payable_hours, non_payable_hours, total_hours).
    A row is payable if whichever of category/leave type is actually set on it has ispayable=True."""
    total = entries.aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    payable = entries.filter(
        Q(**{f'{category_field}__ispayable': True}) | Q(leavetypeid__ispayable=True)
    ).aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    return payable, total - payable, total


def _last_entry_prefill(entries, category_field, category_prefix):
    """Given one employee's entries queryset (any header/month), return
    (category_selection, shifttype, hours) from their most recently created
    entry — used to prefill the + Add Entry row, mirroring how a new
    Operations sheet carries forward each crew member's last category."""
    last = entries.order_by('-pk').first()
    if not last:
        return '', '', None
    category = getattr(last, category_field)
    if category:
        selection = f'{category_prefix}{category.pk}'
    elif last.leavetypeid_id:
        selection = f'lt_{last.leavetypeid_id}'
    else:
        selection = ''
    return selection, last.shifttype or '', last.hoursworked


# Create your views here.
@login_required(login_url = 'login')
def new_timesheet(request):
    if request.user.access_level != 9:
            return redirect('profile')

    al = request.user.access_level

    # al=9 Maintenance Crew → MainHeader
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
    log_action(request.user, 'Created', 'MainHeader', header.mainheaderid, new_values={'overallstatus': 'Draft'})
    return redirect('add_entry', pk=header.mainheaderid)


@login_required(login_url='login')
def delete_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid=request.user, overallstatus='Draft')
        log_action(request.user, 'Deleted', 'MainHeader', header.mainheaderid, old_values={'overallstatus': header.overallstatus})
        header.delete()
    return redirect('my_drafts')


@login_required(login_url = 'login')
def add_entry(request, pk):
    if request.user.access_level != 9:
            return redirect('profile')
    
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
            startdate_str = request.POST.get('startdate')
            hoursworked_str = request.POST.get('hoursworked')
            existing_entry = MainEntry.objects.filter(mainentryid=entryid).first() if entryid else None
            leave_error = _validate_leave_entry(request.user, leavetypeid, startdate_str, hoursworked_str, exclude_entry=existing_entry)

            date_error = None
            if workcategoryid and not revision_mode and not leave_error:
                try:
                    if date.fromisoformat(startdate_str) > timezone.now().date():
                        date_error = 'Date cannot be a future date for this work category.'
                except (TypeError, ValueError):
                    date_error = 'Please enter a valid date.'

            if leave_error:
                messages.error(request, leave_error)
            elif date_error:
                messages.error(request, date_error)
            elif entryid:
                if revision_mode:
                    entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header, linestatus='Rejected')
                else:
                    entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                old_values = {'hoursworked': str(entry.hoursworked), 'startdate': str(entry.startdate)}
                entry.workcategoryid_id = workcategoryid
                entry.leavetypeid_id = leavetypeid
                entry.sapworkid = request.POST.get('sapworkid') or None
                entry.shifttype = request.POST.get('shifttype')
                entry.hoursworked = hoursworked_str
                entry.startdate = startdate_str
                entry.entrydescription = request.POST.get('entrydescription') or None
                if revision_mode:
                    entry.linestatus = 'New'
                    entry.approvedat = None
                    entry.approvedby = None
                    entry.supervisornote = None
                entry.save()
                log_action(request.user, 'Updated', 'MainEntry', entry.mainentryid, old_values=old_values,
                           new_values={'hoursworked': str(entry.hoursworked), 'startdate': str(entry.startdate)})
            elif not revision_mode:
                entry = MainEntry.objects.create(
                    mainheaderid=header,
                    workcategoryid_id=workcategoryid,
                    leavetypeid_id=leavetypeid,
                    sapworkid=request.POST.get('sapworkid') or None,
                    shifttype=request.POST.get('shifttype'),
                    hoursworked=hoursworked_str,
                    startdate=startdate_str,
                    entrydescription=request.POST.get('entrydescription') or None,
                )
                log_action(request.user, 'Created', 'MainEntry', entry.mainentryid,
                           new_values={'hoursworked': str(entry.hoursworked), 'startdate': str(entry.startdate)})

        elif action == 'update_crew' and not revision_mode:
            header.crewid_id = request.POST.get('crewid') or None
            header.save()

        elif action == 'delete_entry':
            entry_id = request.POST.get('entryid')
            qs = MainEntry.objects.filter(mainentryid=entry_id, mainheaderid=header, linestatus='Rejected') if revision_mode \
                else MainEntry.objects.filter(mainentryid=entry_id, mainheaderid=header)
            entry = qs.first()
            if entry:
                log_action(request.user, 'Deleted', 'MainEntry', entry.mainentryid,
                           old_values={'hoursworked': str(entry.hoursworked), 'startdate': str(entry.startdate)})
                entry.delete()

        elif action == 'submit_timesheet' and not revision_mode:
            if not MainEntry.objects.filter(mainheaderid=header).exists():
                return redirect('add_entry', pk=header.mainheaderid)
            old_status = header.overallstatus
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            MainEntry.objects.filter(mainheaderid=header).update(linestatus='New')
            log_action(request.user, 'Submitted', 'MainHeader', header.mainheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
            return redirect('my_drafts')

        elif action == 'resubmit' and revision_mode:
            if not MainEntry.objects.filter(mainheaderid=header, linestatus='Rejected').exists():
                old_status = header.overallstatus
                header.overallstatus = 'Submitted'
                header.submittedat = timezone.now()
                header.save()
                log_action(request.user, 'Resubmitted', 'MainHeader', header.mainheaderid,
                           old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
                return redirect('my_drafts')

        return redirect('add_entry', pk=header.mainheaderid)

    entries = MainEntry.objects.filter(mainheaderid=header).select_related('workcategoryid', 'leavetypeid')
    workcategories = Workcategory.objects.all()
    # Maintenance Crew (al=9) is hourly — never lieu-eligible, so Lieu Day never appears here.
    leavetypes = LeaveType.objects.filter(isactive=1).exclude(leavetypename=leave_rules.LIEU_DAY_TYPE_NAME)
    payable_hours, non_payable_hours, hours = _payable_hours_split(entries, 'workcategoryid')
    stat_dates, stat_labels = _stat_info()
    this_year = timezone.now().year
    last_category_selection, last_shifttype, last_hours = _last_entry_prefill(
        MainEntry.objects.filter(mainheaderid__employeeid=request.user), 'workcategoryid', 'wc_'
    )

    context = {
        'header': header,
        'entries': entries,
        'workcategories': workcategories,
        'leavetypes': leavetypes,
        'hours': hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'revision_mode': revision_mode,
        'vacation_remaining': leave_rules.get_vacation_remaining(request.user, this_year),
        'floater_available': leave_rules.get_floater_available(request.user, this_year),
        'last_category_selection': last_category_selection,
        'last_shifttype': last_shifttype,
        'last_hours': last_hours,
        **leave_rules.leave_type_ids_context(),
    }
    if revision_mode:
        context['has_rejected'] = entries.filter(linestatus='Rejected').exists()
    else:
        context['crews'] = Crews.objects.all()
        context['today'] = timezone.now().date()
        context['days_remaining'] = 60 - (timezone.now() - header.startedat).days
        # Soft deadline warning: never blocks submission, just flags it as
        # late (for the employee now, and for supervisor/payroll afterward
        # via MainHeader.is_late) so a forgotten timesheet is never
        # impossible to file — only visibly late.
        earliest_date = entries.aggregate(Min('startdate'))['startdate__min']
        if earliest_date:
            deadline = submission_deadline(earliest_date.year, earliest_date.month)
            context['would_be_late'] = timezone.now() > deadline
            context['late_deadline'] = deadline

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
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    hours_approved = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve':
             entryid = request.POST.get('entryid')
             if entryid:
                 entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                 old_status = entry.linestatus
                 entry.linestatus = 'Approved'
                 entry.approvedat = timezone.now()
                 entry.supervisornote = request.POST.get('supervisornote') or None
                 entry.approvedby = request.user
                 entry.save()
                 header.overallstatus = 'In Progress'
                 header.save()
                 log_action(request.user, 'Approved', 'MainEntry', entry.mainentryid,
                            old_values={'linestatus': old_status}, new_values={'linestatus': 'Approved'})

        elif action == 'reject':
             entryid = request.POST.get('entryid')
             if entryid:
                 entry = get_object_or_404(MainEntry, mainentryid=entryid, mainheaderid=header)
                 old_status = entry.linestatus
                 entry.linestatus = 'Rejected'
                 entry.approvedat = timezone.now()
                 entry.supervisornote = request.POST.get('supervisornote') or None
                 entry.approvedby = request.user
                 entry.save()
                 header.overallstatus = 'In Progress'
                 header.save()
                 log_action(request.user, 'Rejected', 'MainEntry', entry.mainentryid,
                            old_values={'linestatus': old_status}, new_values={'linestatus': 'Rejected'})

        elif action == 'bulk_approve':
            entryids = request.POST.getlist('entryids')
            to_approve = MainEntry.objects.filter(mainentryid__in=entryids, mainheaderid=header, linestatus='New')
            if to_approve.exists():
                for entry in to_approve:
                    entry.linestatus = 'Approved'
                    entry.approvedat = timezone.now()
                    entry.supervisornote = None
                    entry.approvedby = request.user
                    entry.save()
                    log_action(request.user, 'Approved', 'MainEntry', entry.mainentryid,
                               old_values={'linestatus': 'New'}, new_values={'linestatus': 'Approved'})
                header.overallstatus = 'In Progress'
                header.save()

        elif action == 'finish_review':
            old_status = header.overallstatus
            if entries.filter(linestatus='Rejected').exists():
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.completedat = timezone.now()
            header.save()
            log_action(request.user, 'ReviewCompleted', 'MainHeader', header.mainheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': header.overallstatus})
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
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
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

    submissions = MainHeader.objects.filter(
        overallstatus='Completed',
        paidat__isnull=True,
    ).select_related(
        'employeeid', 'employeeid__roleid__departmentid'
    ).annotate(
        entry_count=Count('mainentry', filter=Q(mainentry__linestatus='Approved')),
        total_hours=Sum('mainentry__hoursworked', filter=Q(mainentry__linestatus='Approved')),
        date_from=Min('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
        date_to=Max('mainentry__startdate', filter=Q(mainentry__linestatus='Approved')),
    ).filter(entry_count__gt=0).order_by('employeeid__lastname', 'employeeid__firstname', '-submittedat')

    return render(request, 'timesheets/payroll_unprocessed.html', {
        'submissions': submissions,
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
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'mark_as_paid':
            header.paidat = timezone.now()
            header.paidby = request.user
            header.save()
            log_action(request.user, 'MarkedPaid', 'MainHeader', header.mainheaderid,
                       old_values={'paidat': None}, new_values={'paidat': str(header.paidat)})
            messages.success(request, f'Payment for {header.employeeid.firstname} {header.employeeid.lastname} marked as complete.')
            return redirect('payroll_unprocessed')

        elif action == 'mark_as_unpaid':
            old_paidat = header.paidat
            header.paidat = None
            header.paidby = None
            header.save()
            log_action(request.user, 'MarkedUnpaid', 'MainHeader', header.mainheaderid,
                       old_values={'paidat': str(old_paidat) if old_paidat else None}, new_values={'paidat': None})
            return redirect('payroll_unprocessed')

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_unprocessed_review.html', {
        'dept': dept,
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def payroll_business_unprocessed(request):
    if request.user.access_level != 7:
        return redirect('profile')

    departments = Department.objects.filter(isactive=1).annotate(
        unpaid_count=Count(
            'roles__user__businessheader',
            filter=Q(
                roles__user__businessheader__overallstatus='Completed',
                roles__user__businessheader__paidat__isnull=True,
            ),
            distinct=True
        )
    )

    return render(request, 'timesheets/payroll_business_unprocessed.html', {
        'departments': departments,
    })


@login_required(login_url='login')
def payroll_business_unprocessed_dept(request, dept_id):
    if request.user.access_level != 7:
        return redirect('profile')

    dept = get_object_or_404(Department, departmentid=dept_id)
    employees = User.objects.filter(roleid__departmentid=dept_id, isactive=True)

    submissions = BusinessHeader.objects.filter(
        employeeid__in=employees,
        overallstatus='Completed',
        paidat__isnull=True,
    ).select_related('employeeid').annotate(
        entry_count=Count('businessentry', filter=Q(businessentry__linestatus='Approved')),
        total_hours=Sum('businessentry__hoursworked', filter=Q(businessentry__linestatus='Approved')),
    ).filter(entry_count__gt=0).order_by(
        'employeeid__roleid__accessid__accessid', 'employeeid__lastname', 'employeeid__firstname', '-periodyear', '-periodmonth'
    )

    return render(request, 'timesheets/payroll_business_unprocessed_dept.html', {
        'dept': dept,
        'submissions': submissions,
    })


@login_required(login_url='login')
def payroll_business_unprocessed_review(request, dept_id, pk):
    if request.user.access_level != 7:
        return redirect('profile')

    header = get_object_or_404(
        BusinessHeader.objects.select_related('employeeid__roleid__departmentid'),
        businessheaderid=pk,
    )

    if header.overallstatus != 'Completed':
        return redirect('payroll_business_unprocessed')

    entries = BusinessEntry.objects.filter(
        businessheaderid=header,
    ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')

    payable_hours, non_payable_hours, total_hours = _payable_hours_split(
        entries.filter(linestatus='Approved'), 'businesscategoryid'
    )

    dept_id = header.employeeid.roleid.departmentid_id

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'mark_as_paid':
            header.paidat = timezone.now()
            header.paidby = request.user
            header.save()
            log_action(request.user, 'MarkedPaid', 'BusinessHeader', header.businessheaderid,
                       old_values={'paidat': None}, new_values={'paidat': str(header.paidat)})
            messages.success(
                request,
                f'Payment for {header.employeeid.firstname} {header.employeeid.lastname} '
                f'({header.get_periodmonth_display()} {header.periodyear}) marked as complete.'
            )
            return redirect('payroll_business_unprocessed_dept', dept_id=dept_id)

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_business_unprocessed_review.html', {
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'dept_id': dept_id,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def payroll_processed_maintenance(request):
    if request.user.access_level != 7:
        return redirect('profile')
    employees = User.objects.filter(
        roleid__accessid__accessid=9,
        isactive=True,
        mainheader__paidat__isnull=False,
    ).distinct().select_related('roleid').order_by('lastname', 'firstname')
    return render(request, 'timesheets/payroll_processed_maintenance.html', {'employees': employees})


@login_required(login_url='login')
def payroll_processed_maintenance_employee(request, employee_id):
    if request.user.access_level != 7:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    months = MainEntry.objects.filter(
        mainheaderid__employeeid=employee,
        mainheaderid__paidat__isnull=False,
        linestatus='Approved',
    ).annotate(
        month=TruncMonth('startdate'),
    ).values('month').annotate(
        entry_count=Count('mainentryid'),
        total_hours=Sum('hoursworked'),
    ).order_by('-month')
    return render(request, 'timesheets/payroll_processed_maintenance_employee.html', {
        'employee': employee,
        'months': months,
    })


@login_required(login_url='login')
def payroll_processed_maintenance_month(request, employee_id, year, month):
    if request.user.access_level != 7:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    entries = MainEntry.objects.filter(
        mainheaderid__employeeid=employee,
        mainheaderid__paidat__isnull=False,
        linestatus='Approved',
        startdate__year=year,
        startdate__month=month,
    ).select_related('workcategoryid', 'leavetypeid', 'mainheaderid__paidby').order_by('startdate')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    stat_dates, stat_labels = _stat_info()
    month_date = date(year, month, 1)
    return render(request, 'timesheets/payroll_processed_maintenance_month.html', {
        'employee': employee,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'month_date': month_date,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def payroll_processed_business(request):
    if request.user.access_level != 7:
        return redirect('profile')
    departments = Department.objects.filter(isactive=1).annotate(
        employee_count=Count(
            'roles__user',
            filter=Q(
                roles__user__isactive=True,
                roles__user__businessheader__paidat__isnull=False,
            ),
            distinct=True,
        )
    ).filter(employee_count__gt=0).order_by('departmentname')
    return render(request, 'timesheets/payroll_processed_business.html', {'departments': departments})


@login_required(login_url='login')
def payroll_processed_business_dept(request, dept_id):
    if request.user.access_level != 7:
        return redirect('profile')
    dept = get_object_or_404(Department, departmentid=dept_id)
    employees = User.objects.filter(
        roleid__departmentid=dept_id,
        isactive=True,
        businessheader__paidat__isnull=False,
    ).distinct().select_related('roleid').order_by('lastname', 'firstname')
    return render(request, 'timesheets/payroll_processed_business_dept.html', {
        'dept': dept,
        'employees': employees,
    })


@login_required(login_url='login')
def payroll_processed_business_employee(request, dept_id, employee_id):
    if request.user.access_level != 7:
        return redirect('profile')
    dept = get_object_or_404(Department, departmentid=dept_id)
    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    months = BusinessEntry.objects.filter(
        businessheaderid__employeeid=employee,
        businessheaderid__paidat__isnull=False,
        linestatus='Approved',
    ).annotate(
        month=TruncMonth('dateworked'),
    ).values('month').annotate(
        entry_count=Count('businessentryid'),
        total_hours=Sum('hoursworked'),
    ).order_by('-month')
    return render(request, 'timesheets/payroll_processed_business_employee.html', {
        'dept': dept,
        'employee': employee,
        'months': months,
    })


@login_required(login_url='login')
def payroll_processed_business_month(request, dept_id, employee_id, year, month):
    if request.user.access_level != 7:
        return redirect('profile')
    dept = get_object_or_404(Department, departmentid=dept_id)
    employee = get_object_or_404(User, employeeid=employee_id, isactive=True)
    entries = BusinessEntry.objects.filter(
        businessheaderid__employeeid=employee,
        businessheaderid__paidat__isnull=False,
        linestatus='Approved',
        dateworked__year=year,
        dateworked__month=month,
    ).select_related('businesscategoryid', 'leavetypeid', 'businessheaderid__paidby').order_by('dateworked')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'businesscategoryid')
    month_date = date(year, month, 1)
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_processed_business_month.html', {
        'dept': dept,
        'employee': employee,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'month_date': month_date,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'year': year,
        'month': month,
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

    days = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).exclude(
        opsheaderid__in=unpaid_header_ids
    ).values('shiftdate').annotate(
        sheet_count=Count('opsheaderid'),
        day_count=Count('opsheaderid', filter=Q(shifttype='Day')),
        night_count=Count('opsheaderid', filter=Q(shifttype='Night')),
    ).order_by('shiftdate')

    return render(request, 'timesheets/payroll_ops_daily_month.html', {
        'days': days,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
    })


@login_required(login_url='login')
def payroll_ops_daily_day(request, year, month, day):
    if request.user.access_level != 7:
        return redirect('profile')

    unpaid_header_ids = OperationsEntry.objects.filter(
        linestatus='Approved',
        paidat__isnull=True,
    ).values_list('opsheaderid', flat=True)

    target_date = date(year, month, day)

    shifts = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=target_date,
    ).exclude(
        opsheaderid__in=unpaid_header_ids
    ).values('shifttype').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
    ).order_by('shifttype')

    return render(request, 'timesheets/payroll_ops_daily_day.html', {
        'target_date': target_date,
        'shifts': shifts,
        'year': year,
        'month': month,
        'day': day,
        'month_date': date(year, month, 1),
    })


@login_required(login_url='login')
def payroll_ops_daily_shift(request, year, month, day, shifttype):
    if request.user.access_level != 7:
        return redirect('profile')

    unpaid_header_ids = OperationsEntry.objects.filter(
        linestatus='Approved',
        paidat__isnull=True,
    ).values_list('opsheaderid', flat=True)

    target_date = date(year, month, day)

    headers = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=target_date,
        shifttype=shifttype,
    ).exclude(
        opsheaderid__in=unpaid_header_ids
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).prefetch_related(
        Prefetch(
            'operationsentry_set',
            queryset=OperationsEntry.objects.filter(
                linestatus='Approved'
            ).select_related(
                'employeeid', 'contractid', 'accountid', 'opscategoryid', 'leavetypeid'
            ).order_by('employeeid__lastname', 'employeeid__firstname'),
        )
    ).order_by('crewid__crewname', 'section', 'shifterid__lastname', 'shifterid__firstname')

    return render(request, 'timesheets/payroll_ops_daily_shift.html', {
        'headers': headers,
        'target_date': target_date,
        'shifttype': shifttype,
        'year': year,
        'month': month,
        'day': day,
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
        'opsheaderid__shifterid', 'opsheaderid__crewid', 'contractid', 'accountid', 'opscategoryid', 'paidby'
    ).order_by('opsheaderid__shiftdate', 'opsheaderid__shifttype')

    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'opscategoryid')
    bonus = OperationsBonus.objects.filter(employeeid=member, bonusmonth=month_date).first()

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/payroll_ops_member_month.html', {
        'member': member,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_date': month_date,
        'bonus': bonus,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def payroll_employee_bonuses(request):
    if request.user.access_level != 7:
        return redirect('profile')
    departments = Department.objects.filter(isactive=1).annotate(
        pending_count=Count(
            'roles__user__bonuses',
            filter=Q(roles__user__bonuses__appliedbypayroll__isnull=True),
            distinct=True,
        )
    )
    return render(request, 'timesheets/payroll_employee_bonuses.html', {'departments': departments})


@login_required(login_url='login')
def payroll_employee_bonuses_dept(request, dept_id):
    if request.user.access_level != 7:
        return redirect('profile')
    dept = get_object_or_404(Department, departmentid=dept_id)

    if request.method == 'POST' and request.POST.get('action') == 'apply':
        bonus = get_object_or_404(
            EmployeeBonus, employeebonusid=request.POST.get('bonusid'),
            employeeid__roleid__departmentid=dept_id, appliedbypayroll__isnull=True,
        )
        bonus.appliedbypayroll = request.user
        bonus.appliedatpayroll = timezone.now()
        bonus.save()
        return redirect('payroll_employee_bonuses_dept', dept_id=dept_id)

    bonuses = EmployeeBonus.objects.filter(
        employeeid__roleid__departmentid=dept_id, appliedbypayroll__isnull=True,
    ).select_related('employeeid', 'assignedby').order_by('employeeid__lastname', 'employeeid__firstname', '-periodend')

    return render(request, 'timesheets/payroll_employee_bonuses_dept.html', {
        'dept': dept,
        'bonuses': bonuses,
    })


@login_required(login_url='login')
def superintendent_approved(request):
    if request.user.access_level != 2:
        return redirect('profile')
    employees = User.objects.filter(
        supervisorid=request.user, isactive=True,
    ).order_by('lastname', 'firstname')
    return render(request, 'timesheets/superintendent_approved.html', {'employees': employees})


@login_required(login_url='login')
def superintendent_approved_employee(request, employee_id):
    if request.user.access_level != 2:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, supervisorid=request.user)
    periods = BusinessHeader.objects.filter(
        employeeid=employee,
        overallstatus='Completed',
    ).values('periodyear', 'periodmonth').annotate(
        sheet_count=Count('businessheaderid'),
        total_hours=Sum('businessentry__hoursworked'),
    ).order_by('-periodyear', '-periodmonth')
    return render(request, 'timesheets/superintendent_approved_employee.html', {
        'employee': employee,
        'periods': periods,
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def superintendent_approved_month(request, employee_id, year, month):
    if request.user.access_level != 2:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, supervisorid=request.user)
    headers = BusinessHeader.objects.filter(
        employeeid=employee,
        overallstatus='Completed',
        periodyear=year,
        periodmonth=month,
    )
    entries = BusinessEntry.objects.filter(
        businessheaderid__in=headers,
    ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(
        entries.filter(linestatus='Approved'), 'businesscategoryid'
    )
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/superintendent_approved_month.html', {
        'employee': employee,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_name': _MONTH_NAMES.get(month, ''),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def superintendent_ops_daily(request):
    if request.user.access_level != 2:
        return redirect('profile')

    current_year = timezone.now().year
    selected_year = int(request.GET.get('year', current_year))

    months = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=selected_year,
    ).annotate(
        month=TruncMonth('shiftdate')
    ).values('month').annotate(
        sheet_count=Count('opsheaderid')
    ).order_by('-month')

    archive_years = [
        d.year for d in OperationsHeader.objects.filter(
            overallstatus='Completed',
        ).dates('shiftdate', 'year')
        if d.year != current_year
    ]

    return render(request, 'timesheets/superintendent_ops_daily.html', {
        'months': months,
        'current_year': current_year,
        'selected_year': selected_year,
        'archive_years': archive_years,
    })


@login_required(login_url='login')
def superintendent_ops_daily_month(request, year, month):
    if request.user.access_level != 2:
        return redirect('profile')

    days = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).values('shiftdate').annotate(
        sheet_count=Count('opsheaderid'),
        day_count=Count('opsheaderid', filter=Q(shifttype='Day')),
        night_count=Count('opsheaderid', filter=Q(shifttype='Night')),
    ).order_by('shiftdate')

    return render(request, 'timesheets/superintendent_ops_daily_month.html', {
        'days': days,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
    })


@login_required(login_url='login')
def superintendent_ops_daily_day(request, year, month, day):
    if request.user.access_level != 2:
        return redirect('profile')

    target_date = date(year, month, day)

    shifts = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=target_date,
    ).values('shifttype').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
    ).order_by('shifttype')

    return render(request, 'timesheets/superintendent_ops_daily_day.html', {
        'target_date': target_date,
        'shifts': shifts,
        'year': year,
        'month': month,
        'day': day,
        'month_date': date(year, month, 1),
    })


@login_required(login_url='login')
def superintendent_ops_daily_shift(request, year, month, day, shifttype):
    if request.user.access_level != 2:
        return redirect('profile')

    target_date = date(year, month, day)

    headers = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=target_date,
        shifttype=shifttype,
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).prefetch_related(
        Prefetch(
            'operationsentry_set',
            queryset=OperationsEntry.objects.filter(
                linestatus='Approved'
            ).select_related(
                'employeeid', 'contractid', 'accountid', 'opscategoryid', 'leavetypeid'
            ).order_by('employeeid__lastname', 'employeeid__firstname'),
        )
    ).order_by('crewid__crewname', 'section', 'shifterid__lastname', 'shifterid__firstname')

    return render(request, 'timesheets/superintendent_ops_daily_shift.html', {
        'headers': headers,
        'target_date': target_date,
        'shifttype': shifttype,
        'year': year,
        'month': month,
        'day': day,
        'month_date': date(year, month, 1),
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
        'contractid', 'accountid', 'opscategoryid',
    ).order_by('opsheaderid__shiftdate', 'opsheaderid__shifttype')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'opscategoryid')
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
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
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
        'employeeid', 'contractid', 'accountid', 'opscategoryid', 'paidby'
    )

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'mark_as_paid':
            unpaid_count = opsentries.filter(paidat__isnull=True).count()
            opsentries.filter(paidat__isnull=True).update(paidat=timezone.now(), paidby=request.user)
            log_action(request.user, 'MarkedPaid', 'OperationsHeader', opsheader.opsheaderid,
                       new_values={'entries_paid': unpaid_count})
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
    drafts = MainHeader.objects.filter(
        employeeid=request.user,
        overallstatus__in=['Draft', 'Revision Required', 'Submitted', 'In Progress'],
    ).annotate(
        entry_count=Count('mainentry'),
        total_hours=Sum('mainentry__hoursworked'),
        date_from=Min('mainentry__startdate'),
        date_to=Max('mainentry__startdate')
    ).order_by('-startedat')

    return render(request, 'timesheets/my_drafts.html', {'drafts': drafts})


@login_required(login_url='login')
def view_timesheet(request, pk):
    header = get_object_or_404(MainHeader, mainheaderid=pk, employeeid=request.user)
    entries = MainEntry.objects.filter(mainheaderid=header).select_related('workcategoryid', 'leavetypeid')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/view_timesheet.html', {
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def supervisor_approved(request):
    if request.user.access_level != 3:
        return redirect('profile')
    employees = User.objects.filter(
        supervisorid=request.user, isactive=True,
    ).order_by('lastname', 'firstname')
    return render(request, 'timesheets/supervisor_approved.html', {'employees': employees})


@login_required(login_url='login')
def supervisor_approved_employee(request, employee_id):
    if request.user.access_level != 3:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, supervisorid=request.user)

    if employee.access_level == 9:
        months = MainEntry.objects.filter(
            mainheaderid__employeeid=employee,
            mainheaderid__overallstatus='Completed',
            linestatus='Approved',
        ).annotate(
            month=TruncMonth('startdate'),
        ).values('month').annotate(
            entry_count=Count('mainentryid'),
            total_hours=Sum('hoursworked'),
        ).order_by('-month')
    else:
        periods = BusinessHeader.objects.filter(
            employeeid=employee,
            overallstatus='Completed',
        ).values('periodyear', 'periodmonth').annotate(
            entry_count=Count('businessentry'),
            total_hours=Sum('businessentry__hoursworked'),
        ).order_by('-periodyear', '-periodmonth')
        months = [
            {
                'month': date(p['periodyear'], p['periodmonth'], 1),
                'entry_count': p['entry_count'],
                'total_hours': p['total_hours'],
            }
            for p in periods
        ]

    return render(request, 'timesheets/supervisor_approved_employee.html', {
        'employee': employee,
        'months': months,
    })


@login_required(login_url='login')
def supervisor_approved_month(request, employee_id, year, month):
    if request.user.access_level != 3:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, supervisorid=request.user)

    if employee.access_level == 9:
        entries = MainEntry.objects.filter(
            mainheaderid__employeeid=employee,
            mainheaderid__overallstatus='Completed',
            linestatus='Approved',
            startdate__year=year,
            startdate__month=month,
        ).select_related(
            'mainheaderid', 'workcategoryid', 'leavetypeid',
        ).order_by('startdate')
        payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    else:
        business_entries = BusinessEntry.objects.filter(
            businessheaderid__employeeid=employee,
            businessheaderid__overallstatus='Completed',
            linestatus='Approved',
            dateworked__year=year,
            dateworked__month=month,
        ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')
        payable_hours, non_payable_hours, total_hours = _payable_hours_split(business_entries, 'businesscategoryid')
        # Normalize onto the same field names supervisor_approved_month.html already
        # renders for MainEntry, so one template serves both domains unchanged.
        entries = [
            SimpleNamespace(
                startdate=e.dateworked,
                workcategoryid=e.businesscategoryid,
                leavetypeid=e.leavetypeid,
                shifttype=e.shifttype,
                hoursworked=e.hoursworked,
                sapworkid=None,
                entrydescription=e.entrydescription,
                linestatus=e.linestatus,
            )
            for e in business_entries
        ]

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/supervisor_approved_month.html', {
        'employee': employee,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def my_timesheets_approved(request):
    if request.user.access_level != 9:
        return redirect('profile')
    months = MainEntry.objects.filter(
        mainheaderid__employeeid=request.user,
        mainheaderid__overallstatus='Completed',
        linestatus='Approved',
    ).annotate(
        month=TruncMonth('startdate'),
    ).values('month').annotate(
        entry_count=Count('mainentryid'),
        total_hours=Sum('hoursworked'),
    ).order_by('-month')
    return render(request, 'timesheets/my_timesheets_approved.html', {'months': months})


@login_required(login_url='login')
def my_timesheets_approved_month(request, year, month):
    if request.user.access_level != 9:
        return redirect('profile')
    entries = MainEntry.objects.filter(
        mainheaderid__employeeid=request.user,
        mainheaderid__overallstatus='Completed',
        linestatus='Approved',
        startdate__year=year,
        startdate__month=month,
    ).select_related('workcategoryid', 'leavetypeid').order_by('startdate')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/my_timesheets_approved_month.html', {
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def my_timesheets_paid(request):
    if request.user.access_level != 9:
        return redirect('profile')
    months = MainEntry.objects.filter(
        mainheaderid__employeeid=request.user,
        mainheaderid__paidat__isnull=False,
        linestatus='Approved',
    ).annotate(
        month=TruncMonth('startdate'),
    ).values('month').annotate(
        entry_count=Count('mainentryid'),
        total_hours=Sum('hoursworked'),
    ).order_by('-month')
    return render(request, 'timesheets/my_timesheets_paid.html', {'months': months})


@login_required(login_url='login')
def my_timesheets_paid_month(request, year, month):
    if request.user.access_level != 9:
        return redirect('profile')
    entries = MainEntry.objects.filter(
        mainheaderid__employeeid=request.user,
        mainheaderid__paidat__isnull=False,
        linestatus='Approved',
        startdate__year=year,
        startdate__month=month,
    ).select_related('workcategoryid', 'leavetypeid', 'mainheaderid__paidby').order_by('startdate')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'workcategoryid')
    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/my_timesheets_paid_month.html', {
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_date': date(year, month, 1),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def new_ops_sheet(request):
    if request.user.access_level != 5:
        return redirect('profile')

    today = timezone.now().date()
    active_coverages = CrewCoverage.objects.filter(
        covering_shifter=request.user,
        startdate__lte=today,
    ).filter(
        Q(enddate__isnull=True) | Q(enddate__gte=today)
    ).select_related('home_shifter', 'home_shifter__crewid')

    # Every basket this shifter runs themselves — usually just their one home
    # basket; more than one only if they've picked up a second (e.g. via
    # Transfer Basket) while still running their own. Each is its own filing
    # option, distinct from Coverage (which is someone else's crew, temporarily).
    own_baskets = request.user.get_active_baskets()

    # Build maps for JS: swap the displayed section/crew when the shifter
    # toggles between their own basket(s) and coverage options.
    coverage_sections = {
        str(cov.coverageid): cov.home_shifter.shiftertype or ''
        for cov in active_coverages
    }
    coverage_crews = {
        str(cov.coverageid): (cov.home_shifter.crewid.crewname if cov.home_shifter.crewid else '')
        for cov in active_coverages
    }
    own_basket_sections = {f'{b[0].crewid}:{b[1]}': b[1] for b in own_baskets}
    own_basket_crews = {f'{b[0].crewid}:{b[1]}': b[0].crewname for b in own_baskets}
    own_crewname = request.user.crewid.crewname if request.user.crewid else ''
    default_own_basket = f'{own_baskets[0][0].crewid}:{own_baskets[0][1]}' if own_baskets else ''

    base_context = {
        'header': None,
        'active_coverages': active_coverages,
        'own_shiftertype': request.user.shiftertype or '',
        'own_crewname': own_crewname,
        'own_baskets': own_baskets,
        'default_own_basket': default_own_basket,
        'coverage_sections': coverage_sections,
        'coverage_crews': coverage_crews,
        'own_basket_sections': own_basket_sections,
        'own_basket_crews': own_basket_crews,
    }

    if request.method == 'POST':
        shiftdate = request.POST.get('shiftdate')
        shifttype = request.POST.get('shifttype')
        coverage_id = request.POST.get('coverage_id') or None
        own_basket = request.POST.get('own_basket') or None

        try:
            from datetime import date as _date
            if shiftdate and _date.fromisoformat(shiftdate) > today:
                return render(request, 'timesheets/ops_sheet.html', {
                    **base_context,
                    'coverage_sections': {},
                    'coverage_crews': {},
                    'own_basket_sections': {},
                    'own_basket_crews': {},
                    'error': 'Crew sheets cannot be created for future dates.',
                })
        except ValueError:
            pass

        # Derive section + crew from the basket this sheet is actually for —
        # own home basket, a specific other own basket if running more than
        # one, or the home shifter if this is a coverage sheet — never asked
        # for manually, so a sheet can't get mislabeled with the wrong crew.
        section = None
        crew = None
        cov = None
        if coverage_id:
            cov = active_coverages.filter(coverageid=coverage_id).first()
            if cov:
                section = cov.home_shifter.shiftertype
                crew = cov.home_shifter.crewid
        elif own_basket and ':' in own_basket:
            chosen_crewid, chosen_shiftertype = own_basket.split(':', 1)
            match = next(
                (b for b in own_baskets if str(b[0].crewid) == chosen_crewid and b[1] == chosen_shiftertype),
                None,
            )
            if match:
                crew, section = match
        else:
            section = request.user.shiftertype
            crew = request.user.crewid

        if crew is None:
            error = (
                "The crew you're covering doesn't have a home crew set up yet. Contact your System Admin."
                if coverage_id else
                "Your home crew hasn't been set up yet. Contact your System Admin before starting a crew sheet."
            )
            return render(request, 'timesheets/ops_sheet.html', {**base_context, 'error': error})

        existing = OperationsHeader.objects.filter(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype,
            coverageid_id=coverage_id,
            crewid=crew,
        ).first()
        if existing:
            return redirect('ops_sheet', pk=existing.opsheaderid)

        header = OperationsHeader.objects.create(
            shifterid=request.user,
            shiftdate=shiftdate,
            shifttype=shifttype,
            crewid=crew,
            coverageid_id=coverage_id,
            section=section,
        )
        log_action(request.user, 'Created', 'OperationsHeader', header.opsheaderid, new_values={'overallstatus': 'Draft'})

        # Pre-populate one row per active crew member of THIS basket specifically.
        # Scoped to (shifter, crewid, shiftertype), not just shifter, so a
        # shifter running two baskets never gets the other basket's roster
        # bleeding onto this sheet. Guests aren't crew, so they're never
        # auto-added — still only reachable via + Add Row.
        #
        # Contract is sourced from the employee's own current assignment
        # (User.contractid, set by the Superintendent) whenever they have one
        # — not from their last entry, which could be stale if they've since
        # been reclassified. Falls back to their last entry's contract only
        # if they're not yet classified at all. Account only carries forward
        # from the last entry when the contract hasn't effectively changed
        # (still the same one) — an account tied to a now-different contract
        # wouldn't be valid, so it's left for the Shifter to pick fresh.
        # A crew member with neither a current assignment nor any prior entry
        # has no contract to satisfy the NOT NULL column, so they're skipped
        # here and stay available in the + Add Row picker instead.
        prefill_shifter = cov.home_shifter if coverage_id and cov else request.user
        active_assignments = CrewAssignment.objects.filter(
            shifter=prefill_shifter, crewid=crew, shiftertype=section, enddate__isnull=True
        ).select_related('employee')
        for assignment in active_assignments:
            employee = assignment.employee
            last = OperationsEntry.objects.filter(
                employeeid=employee
            ).order_by('-opsentryid').first()
            contract_id = employee.contractid_id or (last.contractid_id if last else None)
            if not contract_id:
                continue
            account_id = last.accountid_id if last and last.contractid_id == contract_id else None
            OperationsEntry.objects.create(
                opsheaderid=header,
                employeeid=employee,
                contractid_id=contract_id,
                accountid_id=account_id,
                opscategoryid_id=last.opscategoryid_id if last else None,
                hoursworked=0,
                linestatus='Draft',
            )

        return redirect('ops_sheet', pk=header.opsheaderid)

    return render(request, 'timesheets/ops_sheet.html', base_context)


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
            sel = request.POST.get('category_selection', '')
            opscategoryid = sel[3:] if sel.startswith('oc_') else None
            leavetypeid = sel[3:] if sel.startswith('lt_') else None
            row_employee = User.objects.filter(pk=request.POST.get('employeeid')).first()
            hoursworked_str = request.POST.get('hoursworked')
            leave_error = None
            if row_employee:
                leave_error = _validate_leave_entry(row_employee, leavetypeid, str(header.shiftdate), hoursworked_str)

            if leave_error:
                messages.error(request, leave_error)
            else:
                # Contract is never the Shifter's call once the Superintendent
                # has classified this employee — always derive it server-side
                # from their current assignment rather than trust whatever the
                # (normally disabled) field posted. Only an employee with no
                # assigned contract yet falls back to the posted value, from
                # the open picker the form still offers in that case.
                contract_id = row_employee.contractid_id if row_employee and row_employee.contractid_id else request.POST.get('contractid')
                entry = OperationsEntry.objects.create(
                    opsheaderid=header,
                    employeeid_id=request.POST.get('employeeid'),
                    contractid_id=contract_id,
                    accountid_id=request.POST.get('accountid') or None,
                    opscategoryid_id=opscategoryid,
                    leavetypeid_id=leavetypeid,
                    hoursworked=hoursworked_str,
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
                log_action(request.user, 'Created', 'OperationsEntry', entry.opsentryid,
                           new_values={'employeeid': entry.employeeid_id, 'hoursworked': str(entry.hoursworked)})

        elif action == 'delete_row':
            entry_id = request.POST.get('entryid')
            qs = OperationsEntry.objects.filter(opsentryid=entry_id, opsheaderid=header)
            if header.overallstatus == 'Revision Required':
                qs = qs.filter(linestatus='Rejected')
            entry = qs.first()
            if entry:
                log_action(request.user, 'Deleted', 'OperationsEntry', entry.opsentryid,
                           old_values={'employeeid': entry.employeeid_id, 'hoursworked': str(entry.hoursworked)})
                entry.delete()

        elif action == 'submit_sheet' and header.overallstatus == 'Draft':
            if not OperationsEntry.objects.filter(opsheaderid=header).exists():
                return redirect('ops_sheet', pk=header.opsheaderid)
            old_status = header.overallstatus
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            OperationsEntry.objects.filter(opsheaderid=header).update(linestatus='New')
            log_action(request.user, 'Submitted', 'OperationsHeader', header.opsheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
            return redirect('my_ops_sheets')

        elif action == 'edit_row' and header.overallstatus in ('Draft', 'Revision Required'):
            if header.overallstatus == 'Revision Required':
                entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header, linestatus='Rejected')
            else:
                entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header)

            sel = request.POST.get('category_selection', '')
            opscategoryid = sel[3:] if sel.startswith('oc_') else None
            leavetypeid = sel[3:] if sel.startswith('lt_') else None
            hoursworked_str = request.POST.get('hoursworked')
            leave_error = _validate_leave_entry(
                entry.employeeid, leavetypeid, str(header.shiftdate), hoursworked_str, exclude_entry=entry,
            )

            if leave_error:
                messages.error(request, leave_error)
            else:
                old_values = {'hoursworked': str(entry.hoursworked)}
                # Same server-authoritative derivation as add_row — the employee's
                # current assignment wins over whatever was posted, whenever they
                # have one.
                entry.contractid_id = entry.employeeid.contractid_id if entry.employeeid.contractid_id else request.POST.get('contractid')
                entry.accountid_id = request.POST.get('accountid') or None
                entry.opscategoryid_id = opscategoryid
                entry.leavetypeid_id = leavetypeid
                entry.hoursworked = hoursworked_str
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
                log_action(request.user, 'Updated', 'OperationsEntry', entry.opsentryid,
                           old_values=old_values, new_values={'hoursworked': str(entry.hoursworked)})

        elif action == 'resubmit' and header.overallstatus == 'Revision Required':
            OperationsEntry.objects.filter(opsheaderid=header).exclude(linestatus='Approved').update(linestatus='New')
            old_status = header.overallstatus
            header.overallstatus = 'Submitted'
            header.save()
            log_action(request.user, 'Resubmitted', 'OperationsHeader', header.opsheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
            return redirect('my_ops_sheets')

        return redirect('ops_sheet', pk=header.opsheaderid)

    entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
        'employeeid', 'contractid', 'accountid', 'opscategoryid', 'approvedby_capt'
    )

    coverage = header.coverageid
    effective_shifter = coverage.home_shifter if coverage else request.user

    active_assignments = CrewAssignment.objects.filter(
        shifter=effective_shifter, enddate__isnull=True
    ).select_related('employee')

    guest_employees = User.objects.filter(roleid__accessid__accessid=8, isactive=True)

    contracts = Contract.objects.filter(isactive=1)
    opscategories = Opscategory.objects.filter(isactive=1)
    # Every crew member logged here is al=8 (hourly) — never lieu-eligible, so Lieu Day never appears.
    leavetypes = LeaveType.objects.filter(isactive=1).exclude(leavetypename=leave_rules.LIEU_DAY_TYPE_NAME)
    vacation_type = leave_rules.get_leave_type(leave_rules.VACATION_TYPE_NAME)
    floater_type = leave_rules.get_leave_type(leave_rules.FLOATER_TYPE_NAME)

    prefill = {}
    vacation_balances = {}
    crew_members = [a.employee for a in active_assignments] + list(guest_employees)
    if request.user.employmenttype == 'Contract':
        crew_members.append(request.user)
    for member in crew_members:
        last = OperationsEntry.objects.filter(
            employeeid=member
        ).order_by('-opsentryid').first()
        # assigned_contractid is the Superintendent's current classification —
        # when set, the entry form locks Contract to it entirely (the Shifter
        # never picks it). contractid/accountid below are only ever used as
        # the fallback/starting point for an employee who isn't classified yet.
        prefill[member.eid] = {
            'assigned_contractid': member.contractid_id,
            'assigned_contract_label': f'{member.contractid.contractcode} — {member.contractid.contracttitle}' if member.contractid_id else None,
            'contractid': last.contractid_id if last else None,
            'accountid': last.accountid_id if last else None,
            'opscategoryid': last.opscategoryid_id if last else None,
        }
        remaining = leave_rules.get_vacation_remaining(member, header.shiftdate.year)
        vacation_balances[member.eid] = {
            'remaining': str(remaining) if remaining is not None else None,
            'floater_available': leave_rules.get_floater_available(member, header.shiftdate.year),
        }

    # Sheet-level default: whatever contract/account/category was last saved on THIS
    # sheet, so picking it once carries forward to the rest of the crew without
    # reselecting. Per-person prefill (above) still overrides this when that specific
    # person has their own distinct last-used contract/account/category.
    last_on_sheet = entries.order_by('-opsentryid').first()
    sheet_default = {
        'contractid': last_on_sheet.contractid_id if last_on_sheet else None,
        'accountid': last_on_sheet.accountid_id if last_on_sheet else None,
        'opscategoryid': last_on_sheet.opscategoryid_id if last_on_sheet else None,
    }

    stat_dates, stat_labels = _stat_info()
    return render(request, 'timesheets/ops_sheet.html', {
        'header': header,
        'entries': entries,
        'active_assignments': active_assignments,
        'guest_employees': guest_employees,
        'contracts': contracts,
        'opscategories': opscategories,
        'leavetypes': leavetypes,
        'vacation_leavetype_id': vacation_type.leavetypeid if vacation_type else None,
        'floater_leavetype_id': floater_type.leavetypeid if floater_type else None,
        'prefill': prefill,
        'vacation_balances': vacation_balances,
        'sheet_default': sheet_default,
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
        day_count=Count('shiftdate', distinct=True),
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
        overallstatus='Completed'
    ).annotate(
        month=TruncMonth('shiftdate')
    ).values('month').annotate(
        day_count=Count('shiftdate', distinct=True),
    ).order_by('-month')
    return render(request, 'timesheets/my_ops_completed.html', {'months': months})


@login_required(login_url='login')
def my_ops_completed_month(request, year, month):
    if request.user.access_level != 4:
        return redirect('profile')
    days = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate__year=year,
        shiftdate__month=month,
    ).values('shiftdate').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
        day_count=Count('opsheaderid', filter=Q(shifttype='Day'), distinct=True),
        night_count=Count('opsheaderid', filter=Q(shifttype='Night'), distinct=True),
    ).order_by('shiftdate')
    return render(request, 'timesheets/my_ops_completed_month.html', {
        'days': days,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def my_ops_completed_day(request, year, month, day):
    if request.user.access_level != 4:
        return redirect('profile')
    shift_date = date(year, month, day)
    shifts = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=shift_date,
    ).values('shifttype').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
    ).order_by('shifttype')
    return render(request, 'timesheets/my_ops_completed_day.html', {
        'shifts': shifts,
        'shift_date': shift_date,
        'year': year,
        'month': month,
        'day': day,
    })


@login_required(login_url='login')
def my_ops_completed_shift(request, year, month, day, shifttype):
    if request.user.access_level != 4:
        return redirect('profile')
    shift_date = date(year, month, day)
    headers = OperationsHeader.objects.filter(
        overallstatus='Completed',
        shiftdate=shift_date,
        shifttype=shifttype,
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter', 'ohapprovedby_capt'
    ).prefetch_related(
        Prefetch(
            'operationsentry_set',
            queryset=OperationsEntry.objects.select_related(
                'employeeid', 'contractid', 'accountid', 'opscategoryid', 'leavetypeid'
            ).order_by('employeeid__firstname', 'employeeid__lastname'),
        )
    ).order_by('crewid__crewname', 'section', 'shifterid__lastname', 'shifterid__firstname')
    return render(request, 'timesheets/my_ops_completed_shift.html', {
        'headers': headers,
        'shift_date': shift_date,
        'shifttype': shifttype,
        'year': year,
        'month': month,
        'day': day,
    })


def _is_contract_shifter(user):
    return user.access_level == 5 and user.employmenttype == 'Contract'


@login_required(login_url='login')
def my_pay_history(request):
    if not _is_contract_shifter(request.user):
        return redirect('profile')
    months = OperationsEntry.objects.filter(
        employeeid=request.user,
        opsheaderid__overallstatus='Completed',
    ).annotate(
        month=TruncMonth('opsheaderid__shiftdate')
    ).values('month').annotate(
        day_count=Count('opsheaderid__shiftdate', distinct=True),
    ).order_by('-month')
    return render(request, 'timesheets/my_pay_history.html', {'months': months})


@login_required(login_url='login')
def my_pay_history_month(request, year, month):
    if not _is_contract_shifter(request.user):
        return redirect('profile')
    entries = OperationsEntry.objects.filter(
        employeeid=request.user,
        opsheaderid__overallstatus='Completed',
        opsheaderid__shiftdate__year=year,
        opsheaderid__shiftdate__month=month,
    ).select_related(
        'opsheaderid', 'opsheaderid__shifterid', 'contractid', 'accountid', 'opscategoryid', 'leavetypeid'
    ).order_by('opsheaderid__shiftdate', 'opsheaderid__shifttype')
    return render(request, 'timesheets/my_pay_history_month.html', {
        'entries': entries,
        'year': year,
        'month': month,
    })


@login_required(login_url='login')
def delete_ops_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(OperationsHeader, opsheaderid=pk, shifterid=request.user, overallstatus='Draft')
        log_action(request.user, 'Deleted', 'OperationsHeader', header.opsheaderid, old_values={'overallstatus': header.overallstatus})
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

    action_needed_dates = OperationsHeader.objects.filter(
        overallstatus__in=['Submitted', 'In Progress'],
    ).filter(
        Q(ohapprovedby_capt__isnull=True) | Q(ohapprovedby_capt=request.user)
    ).values('shiftdate').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
        in_progress_count=Count('opsheaderid', filter=Q(overallstatus='In Progress'), distinct=True),
    ).order_by('shiftdate')

    pending_revision_sheets = OperationsHeader.objects.filter(
        overallstatus='Revision Required', ohapprovedby_capt=request.user
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter'
    ).annotate(
        entry_count=Count('operationsentry'),
        rejected_count=Count('operationsentry', filter=Q(operationsentry__linestatus='Rejected')),
    ).order_by('shiftdate', 'shifttype')

    return render(request, 'timesheets/ops_approval_inbox.html', {
        'action_needed_dates': action_needed_dates,
        'pending_revision_sheets': pending_revision_sheets,
    })


@login_required(login_url='login')
def ops_approval_inbox_date(request, year, month, day):
    if request.user.access_level != 4:
        return redirect('profile')

    target_date = date(year, month, day)
    shifts = OperationsHeader.objects.filter(
        overallstatus__in=['Submitted', 'In Progress'], shiftdate=target_date,
    ).filter(
        Q(ohapprovedby_capt__isnull=True) | Q(ohapprovedby_capt=request.user)
    ).values('shifttype').annotate(
        sheet_count=Count('opsheaderid', distinct=True),
        in_progress_count=Count('opsheaderid', filter=Q(overallstatus='In Progress'), distinct=True),
    ).order_by('shifttype')

    return render(request, 'timesheets/ops_approval_inbox_date.html', {
        'shifts': shifts,
        'target_date': target_date,
        'year': year,
        'month': month,
        'day': day,
    })


@login_required(login_url='login')
def ops_approval_inbox_shift(request, year, month, day, shifttype):
    if request.user.access_level != 4:
        return redirect('profile')

    target_date = date(year, month, day)
    headers = OperationsHeader.objects.filter(
        overallstatus__in=['Submitted', 'In Progress'], shiftdate=target_date, shifttype=shifttype,
    ).filter(
        Q(ohapprovedby_capt__isnull=True) | Q(ohapprovedby_capt=request.user)
    ).select_related(
        'shifterid', 'crewid', 'coverageid__home_shifter'
    ).order_by('crewid__crewname', 'section', 'shifterid__lastname', 'shifterid__firstname')

    stat_dates, stat_labels = _stat_info()
    panels = []
    for header in headers:
        entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
            'employeeid', 'contractid', 'accountid', 'opscategoryid', 'approvedby_capt'
        )
        panels.append({
            'header': header,
            'entries': entries,
            'has_unreviewed': entries.filter(linestatus='New').exists(),
            'has_rejected': entries.filter(linestatus='Rejected').exists(),
            'is_stat': header.shiftdate in stat_dates,
            'stat_label': stat_labels.get(header.shiftdate, ''),
        })

    return render(request, 'timesheets/ops_approval_inbox_shift.html', {
        'panels': panels,
        'shifttype': shifttype,
        'target_date': target_date,
        'year': year,
        'month': month,
        'day': day,
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
        next_url = request.POST.get('next')

        def _redirect_here():
            return redirect(next_url) if next_url else redirect('review_ops_sheet', pk=pk)

        if action in ('approve', 'reject'):
            entry = get_object_or_404(OperationsEntry, opsentryid=request.POST.get('entryid'), opsheaderid=header)
            old_status = entry.linestatus

            if action == 'approve':
                entry.linestatus = 'Approved'
                entry.approvedby_capt = request.user
                entry.approvedat_capt = timezone.now()
                entry.captainnote = None
                entry.save()

            elif action == 'reject':
                note = request.POST.get('captainnote', '').strip()
                if not note:
                    return _redirect_here()
                entry.captainnote = note
                entry.linestatus = 'Rejected'
                entry.approvedby_capt = request.user
                entry.approvedat_capt = timezone.now()
                entry.save()

            log_action(request.user, entry.linestatus, 'OperationsEntry', entry.opsentryid,
                       old_values={'linestatus': old_status}, new_values={'linestatus': entry.linestatus})

            if not header.ohapprovedby_capt:
                header.ohapprovedby_capt = request.user
                header.overallstatus = 'In Progress'
                header.save()
            elif header.overallstatus == 'Submitted':
                header.overallstatus = 'In Progress'
                header.save()
            return _redirect_here()

        elif action == 'bulk_approve':
            entryids = request.POST.getlist('entryids')
            to_approve = OperationsEntry.objects.filter(opsentryid__in=entryids, opsheaderid=header, linestatus='New')
            if to_approve.exists():
                for entry in to_approve:
                    entry.linestatus = 'Approved'
                    entry.approvedby_capt = request.user
                    entry.approvedat_capt = timezone.now()
                    entry.captainnote = None
                    entry.save()
                    log_action(request.user, 'Approved', 'OperationsEntry', entry.opsentryid,
                               old_values={'linestatus': 'New'}, new_values={'linestatus': 'Approved'})
                if not header.ohapprovedby_capt:
                    header.ohapprovedby_capt = request.user
                    header.overallstatus = 'In Progress'
                    header.save()
                elif header.overallstatus == 'Submitted':
                    header.overallstatus = 'In Progress'
                    header.save()
            return _redirect_here()

        elif action == 'finish_review':
            all_entries = OperationsEntry.objects.filter(opsheaderid=header)
            if all_entries.filter(linestatus='New').exists():
                return _redirect_here()
            old_status = header.overallstatus
            if all_entries.filter(linestatus='Rejected').exists():
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.ohapprovedat_capt = timezone.now()
            header.save()
            log_action(request.user, 'ReviewCompleted', 'OperationsHeader', header.opsheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': header.overallstatus})
            return redirect(next_url) if next_url else redirect('ops_approval_inbox')

    entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
        'employeeid', 'contractid', 'accountid', 'opscategoryid', 'approvedby_capt'
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

        elif action == 'add_series':
            contract_id = request.POST.get('contractid')
            new_series_id = request.POST.get('new_series_id')
            if contract_id and new_series_id:
                contract = get_object_or_404(Contract, contractid=contract_id)
                contract.series.add(new_series_id)

        elif action == 'remove_series':
            contract_id = request.POST.get('contractid')
            remove_series_id = request.POST.get('remove_series_id')
            contract = get_object_or_404(Contract, contractid=contract_id)
            contract.series.remove(remove_series_id)

        elif action == 'add_level':
            contract_id = request.POST.get('contractid')
            new_level_id = request.POST.get('new_level_id')
            if contract_id and new_level_id:
                contract = get_object_or_404(Contract, contractid=contract_id)
                contract.levels.add(new_level_id)

        elif action == 'remove_level':
            contract_id = request.POST.get('contractid')
            remove_level_id = request.POST.get('remove_level_id')
            contract = get_object_or_404(Contract, contractid=contract_id)
            contract.levels.remove(remove_level_id)

        elif action == 'bulk_assign_account':
            bulk_series_id = request.POST.get('bulk_series_id')
            bulk_account_id = request.POST.get('bulk_account_id')
            if bulk_series_id and bulk_account_id:
                series = get_object_or_404(ContractSeries, seriesid=bulk_series_id)
                for contract in series.contracts.filter(isactive=1):
                    ContractAccount.objects.get_or_create(contractid=contract, accountid_id=bulk_account_id)

        series_id = request.POST.get('series_id', '')
        base_url = reverse('contract_account_management')
        return redirect(f'{base_url}?open={series_id}' if series_id else base_url)

    # Every active series is shown as a container, even if it currently has no
    # contracts in it — the Superintendent assigns contracts into these from
    # the page itself now, so an empty series still needs to be visible.
    all_series = ContractSeries.objects.prefetch_related('contracts__contractaccount_set__accountid', 'contracts__series')

    unassigned = Contract.objects.filter(isactive=1).exclude(series__isnull=False).prefetch_related('contractaccount_set__accountid', 'series', 'levels')
    all_accounts = Account.objects.filter(isactive=1)
    all_contracts = Contract.objects.filter(isactive=1).prefetch_related('series', 'levels').order_by('contractcode')
    all_levels = MinerLevel.objects.all()

    return render(request, 'timesheets/contract_account_management.html', {
        'series_list': all_series,
        'all_contracts': all_contracts,
        'all_series': all_series,
        'unassigned': unassigned,
        'all_accounts': all_accounts,
        'all_levels': all_levels,
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

_BUSINESS_SUBMITTERS = [3, 4, 5, 6]
_BUSINESS_REVIEWERS = [2, 3, 4]
_MONTH_NAMES = dict(MONTH_CHOICES)


@login_required(login_url='login')
def new_business_timesheet(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')
    if request.user.access_level == 5 and request.user.employmenttype == 'Contract':
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

        if (year, month) > (now.year, now.month):
            messages.error(request, "You can't start a timesheet for a future month.")
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
        log_action(request.user, 'Created', 'BusinessHeader', header.businessheaderid, new_values={'overallstatus': 'Draft'})
        return redirect('add_business_entry', pk=header.businessheaderid)

    current_year = now.year
    return render(request, 'timesheets/business_new.html', {
        'month_choices': MONTH_CHOICES,
        'year_choices': [current_year - 1, current_year],
        'default_month': now.month,
        'default_year': current_year,
        'current_year': current_year,
        'current_month': now.month,
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
                dateworked_str = request.POST.get('dateworked')
                hoursworked_str = request.POST.get('hoursworked')
                existing_entry = BusinessEntry.objects.filter(businessentryid=entryid).first() if entryid else None
                leave_error = _validate_leave_entry(request.user, lt_id, dateworked_str, hoursworked_str, exclude_entry=existing_entry)
                if leave_error:
                    messages.error(request, leave_error)
                elif entryid:
                    entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header, linestatus='Rejected')
                    old_values = {'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)}
                    entry.businesscategoryid_id = bcat_id
                    entry.leavetypeid_id = lt_id
                    entry.dateworked = dateworked_str
                    entry.shifttype = request.POST.get('shifttype') or None
                    entry.hoursworked = hoursworked_str
                    entry.entrydescription = request.POST.get('entrydescription') or None
                    entry.linestatus = 'New'
                    entry.approvedat = None
                    entry.approvedby = None
                    entry.supervisornote = None
                    entry.save()
                    log_action(request.user, 'Updated', 'BusinessEntry', entry.businessentryid, old_values=old_values,
                               new_values={'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)})

            elif action == 'delete_entry':
                entry = BusinessEntry.objects.filter(
                    businessentryid=request.POST.get('entryid'),
                    businessheaderid=header,
                    linestatus='Rejected',
                ).first()
                if entry:
                    log_action(request.user, 'Deleted', 'BusinessEntry', entry.businessentryid,
                               old_values={'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)})
                    entry.delete()

            elif action == 'resubmit':
                if not BusinessEntry.objects.filter(businessheaderid=header, linestatus='Rejected').exists():
                    old_status = header.overallstatus
                    header.overallstatus = 'Submitted'
                    header.submittedat = timezone.now()
                    header.save()
                    log_action(request.user, 'Resubmitted', 'BusinessHeader', header.businessheaderid,
                               old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
                    return redirect('my_business_drafts')

            return redirect('add_business_entry', pk=header.businessheaderid)

        entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
            'businesscategoryid', 'leavetypeid'
        ).order_by('dateworked')
        payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'businesscategoryid')
        stat_dates, stat_labels = _stat_info()
        this_year = timezone.now().year
        return render(request, 'timesheets/add_business_entry.html', {
            'header': header,
            'entries': entries,
            'business_categories': Businesscategory.objects.filter(isactive=1),
            'leavetypes': LeaveType.objects.filter(isactive=1),
            'total_hours': total_hours,
            'payable_hours': payable_hours,
            'non_payable_hours': non_payable_hours,
            'stat_dates': stat_dates,
            'stat_labels': stat_labels,
            'revision_mode': True,
            'has_rejected': entries.filter(linestatus='Rejected').exists(),
            'vacation_remaining': leave_rules.get_vacation_remaining(request.user, this_year),
            'floater_available': leave_rules.get_floater_available(request.user, this_year),
            'lieu_balance': leave_rules.get_lieu_balance(request.user),
            **leave_rules.leave_type_ids_context(),
        })

    if header.overallstatus != 'Draft':
        entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
            'businesscategoryid', 'leavetypeid'
        ).order_by('dateworked')
        payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'businesscategoryid')
        stat_dates, stat_labels = _stat_info()
        return render(request, 'timesheets/add_business_entry.html', {
            'header': header,
            'entries': entries,
            'total_hours': total_hours,
            'payable_hours': payable_hours,
            'non_payable_hours': non_payable_hours,
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
            dateworked_str = request.POST.get('dateworked')
            hoursworked_str = request.POST.get('hoursworked')
            existing_entry = BusinessEntry.objects.filter(businessentryid=entryid).first() if entryid else None
            leave_error = _validate_leave_entry(request.user, lt_id, dateworked_str, hoursworked_str, exclude_entry=existing_entry)

            if leave_error:
                messages.error(request, leave_error)
            elif entryid:
                entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header)
                old_values = {'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)}
                entry.businesscategoryid_id = bcat_id
                entry.leavetypeid_id = lt_id
                entry.dateworked = dateworked_str
                entry.shifttype = request.POST.get('shifttype') or 'Day'
                entry.hoursworked = hoursworked_str
                entry.entrydescription = request.POST.get('entrydescription') or None
                entry.save()
                log_action(request.user, 'Updated', 'BusinessEntry', entry.businessentryid, old_values=old_values,
                           new_values={'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)})
            else:
                entry = BusinessEntry.objects.create(
                    businessheaderid=header,
                    businesscategoryid_id=bcat_id,
                    leavetypeid_id=lt_id,
                    dateworked=dateworked_str,
                    shifttype=request.POST.get('shifttype') or 'Day',
                    hoursworked=hoursworked_str,
                    entrydescription=request.POST.get('entrydescription') or None,
                )
                log_action(request.user, 'Created', 'BusinessEntry', entry.businessentryid,
                           new_values={'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)})

        elif action == 'delete_entry':
            entry = BusinessEntry.objects.filter(
                businessentryid=request.POST.get('entryid'),
                businessheaderid=header,
            ).first()
            if entry:
                log_action(request.user, 'Deleted', 'BusinessEntry', entry.businessentryid,
                           old_values={'hoursworked': str(entry.hoursworked), 'dateworked': str(entry.dateworked)})
                entry.delete()

        elif action == 'submit_timesheet':
            if not BusinessEntry.objects.filter(businessheaderid=header).exists():
                return redirect('add_business_entry', pk=header.businessheaderid)
            old_status = header.overallstatus
            header.overallstatus = 'Submitted'
            header.submittedat = timezone.now()
            header.save()
            BusinessEntry.objects.filter(businessheaderid=header).update(linestatus='New')
            log_action(request.user, 'Submitted', 'BusinessHeader', header.businessheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': 'Submitted'})
            return redirect('my_business_drafts')

        return redirect('add_business_entry', pk=header.businessheaderid)

    entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
        'businesscategoryid', 'leavetypeid'
    ).order_by('dateworked')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'businesscategoryid')
    stat_dates, stat_labels = _stat_info()
    this_year = timezone.now().year
    last_category_selection, last_shifttype, last_hours = _last_entry_prefill(
        BusinessEntry.objects.filter(businessheaderid__employeeid=request.user), 'businesscategoryid', 'bc_'
    )
    # Soft deadline warning: never blocks submission, just flags it as late
    # (for the employee now, and for supervisor/payroll afterward via
    # BusinessHeader.is_late) so a forgotten timesheet is never impossible
    # to file — only visibly late.
    deadline = submission_deadline(header.periodyear, header.periodmonth)
    would_be_late = timezone.now() > deadline

    return render(request, 'timesheets/add_business_entry.html', {
        'header': header,
        'entries': entries,
        'business_categories': Businesscategory.objects.filter(isactive=1),
        'leavetypes': LeaveType.objects.filter(isactive=1),
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'today': timezone.now().date(),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'vacation_remaining': leave_rules.get_vacation_remaining(request.user, this_year),
        'floater_available': leave_rules.get_floater_available(request.user, this_year),
        'lieu_balance': leave_rules.get_lieu_balance(request.user),
        'last_category_selection': last_category_selection,
        'last_shifttype': last_shifttype,
        'last_hours': last_hours,
        'would_be_late': would_be_late,
        'late_deadline': deadline,
        **leave_rules.leave_type_ids_context(),
    })


@login_required(login_url='login')
def delete_business_draft(request, pk):
    if request.method == 'POST':
        header = get_object_or_404(BusinessHeader, businessheaderid=pk, employeeid=request.user, overallstatus='Draft')
        log_action(request.user, 'Deleted', 'BusinessHeader', header.businessheaderid, old_values={'overallstatus': header.overallstatus})
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
        paid_at=Max('paidat'),
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
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(
        entries.filter(linestatus='Approved'), 'businesscategoryid'
    )
    paid_at = headers.aggregate(Max('paidat'))['paidat__max']
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/my_business_approved_month.html', {
        'year': year,
        'month': month,
        'month_name': _MONTH_NAMES.get(month, ''),
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'paid_at': paid_at,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def my_bonuses(request):
    if request.user.access_level not in _BUSINESS_SUBMITTERS:
        return redirect('profile')

    bonuses = EmployeeBonus.objects.filter(employeeid=request.user).select_related('assignedby')

    return render(request, 'timesheets/my_bonuses.html', {'bonuses': bonuses})


@login_required(login_url='login')
def business_approval_inbox(request):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')

    subordinates = User.objects.filter(supervisorid=request.user).exclude(roleid__accessid__accessid=5)
    status_filter = Q(overallstatus__in=['Submitted', 'In Progress'])
    ownership_filter = Q(employeeid__in=subordinates)

    if request.user.access_level == 4:
        ownership_filter |= Q(employeeid__roleid__accessid__accessid=5) & (
            Q(bh_approvedby_capt__isnull=True) | Q(bh_approvedby_capt=request.user)
        )

    pending = BusinessHeader.objects.filter(
        status_filter, ownership_filter,
    ).select_related('employeeid__roleid').annotate(
        entry_count=Count('businessentry'),
    ).distinct().order_by('employeeid__lastname', 'employeeid__firstname', '-submittedat')

    return render(request, 'timesheets/business_approval_inbox.html', {
        'pending': pending,
        'cards_waiting': pending.count(),
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def review_business_timesheet(request, pk):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')

    subordinates = User.objects.filter(supervisorid=request.user).exclude(roleid__accessid__accessid=5)
    ownership_filter = Q(employeeid__in=subordinates)

    if request.user.access_level == 4:
        ownership_filter |= Q(employeeid__roleid__accessid__accessid=5)

    header = get_object_or_404(BusinessHeader.objects.filter(ownership_filter).distinct(), businessheaderid=pk)

    if header.employeeid.access_level == 5 and header.bh_approvedby_capt and header.bh_approvedby_capt != request.user:
        return redirect('business_approval_inbox')

    if header.overallstatus in ('Completed', 'Revision Required'):
        return redirect('business_approval_inbox')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in ('approve', 'reject'):
            entryid = request.POST.get('entryid')
            if entryid:
                entry = get_object_or_404(BusinessEntry, businessentryid=entryid, businessheaderid=header)
                old_status = entry.linestatus
                entry.linestatus = 'Approved' if action == 'approve' else 'Rejected'
                entry.approvedat = timezone.now()
                entry.supervisornote = request.POST.get('supervisornote') or None
                entry.approvedby = request.user
                entry.save()
                header.overallstatus = 'In Progress'
                if header.employeeid.access_level == 5 and not header.bh_approvedby_capt:
                    header.bh_approvedby_capt = request.user
                header.save()
                log_action(request.user, entry.linestatus, 'BusinessEntry', entry.businessentryid,
                           old_values={'linestatus': old_status}, new_values={'linestatus': entry.linestatus})
                if action == 'approve' and entry.leavetypeid_id and entry.leavetypeid.leavetypename == leave_rules.LIEU_DAY_TYPE_NAME:
                    leave_rules.consume_lieu_day(header.employeeid, entry)

        elif action == 'bulk_approve':
            entryids = request.POST.getlist('entryids')
            to_approve = BusinessEntry.objects.filter(businessentryid__in=entryids, businessheaderid=header, linestatus='New')
            if to_approve.exists():
                for entry in to_approve:
                    entry.linestatus = 'Approved'
                    entry.approvedat = timezone.now()
                    entry.supervisornote = None
                    entry.approvedby = request.user
                    entry.save()
                    log_action(request.user, 'Approved', 'BusinessEntry', entry.businessentryid,
                               old_values={'linestatus': 'New'}, new_values={'linestatus': 'Approved'})
                    if entry.leavetypeid_id and entry.leavetypeid.leavetypename == leave_rules.LIEU_DAY_TYPE_NAME:
                        leave_rules.consume_lieu_day(header.employeeid, entry)
                header.overallstatus = 'In Progress'
                if header.employeeid.access_level == 5 and not header.bh_approvedby_capt:
                    header.bh_approvedby_capt = request.user
                header.save()

        elif action == 'finish_review':
            old_status = header.overallstatus
            has_rejected_now = BusinessEntry.objects.filter(businessheaderid=header, linestatus='Rejected').exists()
            if has_rejected_now:
                header.overallstatus = 'Revision Required'
            else:
                header.overallstatus = 'Completed'
                header.completedat = timezone.now()
            header.save()
            log_action(request.user, 'ReviewCompleted', 'BusinessHeader', header.businessheaderid,
                       old_values={'overallstatus': old_status}, new_values={'overallstatus': header.overallstatus})
            return redirect('business_approval_inbox')

        return redirect('review_business_timesheet', pk=header.businessheaderid)

    entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
        'businesscategoryid', 'leavetypeid', 'approvedby'
    ).order_by('dateworked')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(entries, 'businesscategoryid')
    hours_approved = entries.filter(linestatus='Approved').aggregate(Sum('hoursworked'))['hoursworked__sum'] or 0
    has_unreviewed = entries.filter(linestatus='New').exists()
    has_rejected = entries.filter(linestatus='Rejected').exists()
    stat_dates, stat_labels = _stat_info()

    return render(request, 'timesheets/review_business_timesheet.html', {
        'header': header,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'hours_approved': hours_approved,
        'has_unreviewed': has_unreviewed,
        'has_rejected': has_rejected,
        'month_names': _MONTH_NAMES,
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
    })


@login_required(login_url='login')
def mine_captain_approved(request):
    if request.user.access_level != 4:
        return redirect('profile')
    employees = User.objects.filter(
        roleid__accessid__accessid=5, isactive=True,
    ).order_by('lastname', 'firstname')
    return render(request, 'timesheets/mine_captain_approved.html', {'employees': employees})


@login_required(login_url='login')
def mine_captain_approved_employee(request, employee_id):
    if request.user.access_level != 4:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, roleid__accessid__accessid=5)
    periods = BusinessHeader.objects.filter(
        employeeid=employee,
        overallstatus='Completed',
    ).values('periodyear', 'periodmonth').annotate(
        sheet_count=Count('businessheaderid'),
        total_hours=Sum('businessentry__hoursworked'),
    ).order_by('-periodyear', '-periodmonth')
    return render(request, 'timesheets/mine_captain_approved_employee.html', {
        'employee': employee,
        'periods': periods,
        'month_names': _MONTH_NAMES,
    })


@login_required(login_url='login')
def mine_captain_approved_month(request, employee_id, year, month):
    if request.user.access_level != 4:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, roleid__accessid__accessid=5)
    headers = BusinessHeader.objects.filter(
        employeeid=employee,
        overallstatus='Completed',
        periodyear=year,
        periodmonth=month,
    ).select_related('bh_approvedby_capt')
    entries = BusinessEntry.objects.filter(
        businessheaderid__in=headers,
    ).select_related('businesscategoryid', 'leavetypeid').order_by('dateworked')
    payable_hours, non_payable_hours, total_hours = _payable_hours_split(
        entries.filter(linestatus='Approved'), 'businesscategoryid'
    )
    stat_dates, stat_labels = _stat_info()
    reviewed_header = headers.exclude(bh_approvedby_capt__isnull=True).order_by('-completedat').first()
    return render(request, 'timesheets/mine_captain_approved_month.html', {
        'employee': employee,
        'entries': entries,
        'total_hours': total_hours,
        'payable_hours': payable_hours,
        'non_payable_hours': non_payable_hours,
        'year': year,
        'month': month,
        'month_name': _MONTH_NAMES.get(month, ''),
        'stat_dates': stat_dates,
        'stat_labels': stat_labels,
        'reviewer': reviewed_header.bh_approvedby_capt if reviewed_header else None,
        'reviewed_at': reviewed_header.completedat if reviewed_header else None,
    })


@login_required(login_url='login')
def bonus_members(request):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')
    employees = User.objects.filter(
        supervisorid=request.user, isactive=True,
    ).order_by('lastname', 'firstname')
    return render(request, 'timesheets/bonus_members.html', {'employees': employees})


@login_required(login_url='login')
def bonus_employee_detail(request, employee_id):
    if request.user.access_level not in _BUSINESS_REVIEWERS:
        return redirect('profile')
    employee = get_object_or_404(User, employeeid=employee_id, supervisorid=request.user)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add':
            bonustype = request.POST.get('bonustype', '').strip()
            periodstart = request.POST.get('periodstart', '').strip()
            periodend = request.POST.get('periodend', '').strip()
            bonusratecode = request.POST.get('bonusratecode', '').strip()
            notes = request.POST.get('notes', '').strip() or None
            if not all([bonustype, periodstart, periodend, bonusratecode]):
                messages.error(request, "All fields are required to assign a bonus.")
            else:
                EmployeeBonus.objects.create(
                    employeeid=employee,
                    bonustype=bonustype,
                    periodstart=periodstart,
                    periodend=periodend,
                    bonusratecode=bonusratecode,
                    notes=notes,
                    assignedby=request.user,
                )
                messages.success(request, "Bonus assigned.")

        elif action == 'edit':
            bonus = get_object_or_404(
                EmployeeBonus, employeebonusid=request.POST.get('bonusid'),
                employeeid=employee, appliedbypayroll__isnull=True,
            )
            bonus.bonustype = request.POST.get('bonustype', '').strip() or bonus.bonustype
            bonus.periodstart = request.POST.get('periodstart') or bonus.periodstart
            bonus.periodend = request.POST.get('periodend') or bonus.periodend
            bonus.bonusratecode = request.POST.get('bonusratecode', '').strip() or bonus.bonusratecode
            bonus.notes = request.POST.get('notes', '').strip() or None
            bonus.save()
            messages.success(request, "Bonus updated.")

        elif action == 'delete':
            EmployeeBonus.objects.filter(
                employeebonusid=request.POST.get('bonusid'),
                employeeid=employee, appliedbypayroll__isnull=True,
            ).delete()
            messages.success(request, "Bonus removed.")

        return redirect('bonus_employee_detail', employee_id=employee_id)

    bonuses = EmployeeBonus.objects.filter(employeeid=employee).select_related('assignedby').order_by('-periodend')
    return render(request, 'timesheets/bonus_employee_detail.html', {
        'employee': employee,
        'bonuses': bonuses,
        'bonus_type_choices': BONUS_TYPE_CHOICES,
        'rate_codes': BONUS_RATE_CODES,
    })


@login_required(login_url='login')
def audit_log_view(request):
    if request.user.access_level != 1:
        return redirect('profile')

    entries = Auditlog.objects.select_related('employeeid').order_by('-timestamp')

    table = request.GET.get('table', '').strip()
    action = request.GET.get('action', '').strip()
    employee = request.GET.get('employee', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if table:
        entries = entries.filter(tablename=table)
    if action:
        entries = entries.filter(action=action)
    if employee:
        entries = entries.filter(
            Q(employeeid__firstname__icontains=employee) |
            Q(employeeid__lastname__icontains=employee) |
            Q(employeeid__employeeid__icontains=employee)
        )
    if date_from:
        entries = entries.filter(timestamp__date__gte=date_from)
    if date_to:
        entries = entries.filter(timestamp__date__lte=date_to)

    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    tables = Auditlog.objects.order_by('tablename').values_list('tablename', flat=True).distinct()
    actions = Auditlog.objects.order_by('action').values_list('action', flat=True).distinct()

    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'timesheets/audit_log.html', {
        'page_obj': page_obj,
        'tables': tables,
        'actions': actions,
        'selected_table': table,
        'selected_action': action,
        'employee': employee,
        'date_from': date_from,
        'date_to': date_to,
        'querystring': querystring.urlencode(),
    })


@login_required(login_url='login')
def settings_page(request):
    if request.user.access_level != 1:
        return redirect('profile')

    if request.method == 'POST' and request.POST.get('action') == 'populate_stat_holidays':
        year = request.POST.get('year', '').strip()
        year = int(year) if year.isdigit() else timezone.now().year
        output = StringIO()
        call_command('populate_stat_holidays', year, stdout=output)
        log_action(request.user, 'PopulateStatHolidays', 'StatHoliday', year, new_values={'year': year})
        messages.success(request, output.getvalue().strip() or f'Stat holidays populated for {year}.')
        return redirect('settings_page')

    if request.method == 'POST' and request.POST.get('action') == 'toggle_stat_holiday':
        sh = get_object_or_404(StatHoliday, statid=request.POST.get('statid'))
        old_isactive = sh.isactive
        sh.isactive = 0 if sh.isactive else 1
        sh.save()
        log_action(request.user, 'Muted' if sh.isactive == 0 else 'Unmuted', 'StatHoliday', sh.statid,
                   old_values={'isactive': old_isactive}, new_values={'isactive': sh.isactive})
        return redirect('settings_page')

    stat_holidays = StatHoliday.objects.all().order_by('statdate')
    years_map = {}
    for sh in stat_holidays:
        years_map.setdefault(sh.statdate.year, []).append(sh)
    year_cards = [
        {
            'year': year, 'holidays': holidays,
            'active_count': sum(1 for sh in holidays if sh.isactive),
            'muted_count': sum(1 for sh in holidays if not sh.isactive),
        }
        for year, holidays in sorted(years_map.items(), reverse=True)
    ]

    return render(request, 'timesheets/settings_page.html', {
        'current_year': timezone.now().year,
        'year_cards': year_cards,
    })
