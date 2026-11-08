"""Timesheet Search: one shared page for System Admin (1) and Payroll (7).

System Admin, read-only:
  - Drafts (and sheets sent back for revision) are listed but cannot be opened:
    that work is still in the employee's hands. Hours are hidden too.
  - Submitted, approved and paid sheets open read-only. Each open is written
    to the Audit Log as a 'Viewed' entry.
  - Bonuses are listed with their status only. The rate code and notes stay
    hidden, because they are pay information.
Payroll:
  - Only approved (ready to pay) and paid sheets, and bonuses that have
    reached payroll (Submitted) or that payroll has applied.
  - Each row links into the existing Payroll page for that record, where the
    pay actions already live.

Entry-level filters (person on a crew sheet, contract, date ranges on
Maintenance sheets) go through subqueries, never joins. A join on the entry
table would fan out the Sum/Count annotations and inflate hours.
"""
import calendar
from datetime import date, datetime

from django.utils import timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from users.models import Department, User
from .audit import log_action
from .models import (
    BusinessEntry, BusinessHeader, Contract, Crews, EmployeeBonus, MainEntry,
    MainHeader, OperationsBonus, OperationsEntry, OperationsHeader,
)
from .views import _payable_hours_split, _stat_info, _worked_hours_breakdown

SYSADMIN = 1
PAYROLL = 7

WORKFLOW_CHOICES = [
    ('maintenance', 'Maintenance'),
    ('business', 'Business'),
    ('ops', 'Daily Crew'),
    ('crew_bonus', 'Crew Bonus'),
    ('employee_bonus', 'Employee Bonus'),
]
STATUS_CHOICES = [
    ('draft', 'Draft'),
    ('submitted', 'Submitted / Under review'),
    ('approved', 'Approved (awaiting payroll)'),
    ('paid', 'Paid / Applied'),
]
PAYROLL_STATUSES = {'approved', 'paid'}

# A header's overallstatus -> the search's status bucket. Completed is split
# into approved/paid by the paid flag, not here.
_HEADER_BUCKETS = {
    'Draft': 'draft',
    'Revision Required': 'draft',
    'Submitted': 'submitted',
    'In Progress': 'submitted',
}
_HEADER_LABELS = {
    'Draft': 'Draft',
    'Revision Required': 'Revision required',
    'Submitted': 'Submitted',
    'In Progress': 'Under review',
}
_BONUS_BUCKETS = {'Draft': 'draft', 'Submitted': 'approved', 'Applied': 'paid'}
_BONUS_LABELS = {'Draft': 'Draft', 'Submitted': 'Awaiting payroll', 'Applied': 'Applied'}


def _d(d, year=True):
    """'Nov 8, 2026' (or 'Nov 8') without the Linux-only %-d format code.
    Datetimes are shown in local time, so a late-evening payment isn't
    labelled with the next day's UTC date."""
    if isinstance(d, datetime):
        d = timezone.localtime(d)
    return f"{d:%b} {d.day}, {d.year}" if year else f"{d:%b} {d.day}"


def _parse_date(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def _person_q(q, prefix=''):
    """Every word typed must match the first name, last name or payroll ID,
    so 'jane doe' and 'doe 1234' both work."""
    cond = Q()
    for word in q.split():
        cond &= (
            Q(**{f'{prefix}firstname__icontains': word})
            | Q(**{f'{prefix}lastname__icontains': word})
            | Q(**{f'{prefix}employeeid__icontains': word})
        )
    return cond


def _header_bucket(overallstatus, is_paid):
    if overallstatus == 'Completed':
        return 'paid' if is_paid else 'approved'
    return _HEADER_BUCKETS.get(overallstatus, 'draft')


def _header_label(overallstatus, is_paid):
    if overallstatus == 'Completed':
        return 'Paid' if is_paid else 'Approved'
    return _HEADER_LABELS.get(overallstatus, overallstatus)


def _status_filter_for_headers(statuses):
    """Q over a header's overallstatus/paidat for the chosen buckets. Daily Crew
    sheets have no header-level paidat and are filtered after the query."""
    cond = Q(pk__in=[])
    if 'draft' in statuses:
        cond |= Q(overallstatus__in=['Draft', 'Revision Required'])
    if 'submitted' in statuses:
        cond |= Q(overallstatus__in=['Submitted', 'In Progress'])
    if 'approved' in statuses:
        cond |= Q(overallstatus='Completed', paidat__isnull=True)
    if 'paid' in statuses:
        cond |= Q(overallstatus='Completed', paidat__isnull=False)
    return cond


def _month_key_range(date_from, date_to):
    lo = date_from.year * 100 + date_from.month if date_from else None
    hi = date_to.year * 100 + date_to.month if date_to else None
    return lo, hi


def _person_row(emp):
    return {
        'name': f'{emp.firstname} {emp.lastname}',
        'employeeid': emp.employeeid,
        'role': emp.roleid.rolename if emp.roleid_id else '',
    }


def _search(user, f):
    """Return the result rows for the filters in f, newest first."""
    is_admin = user.access_level == SYSADMIN
    statuses = set(f['statuses'])
    if not is_admin:
        statuses &= PAYROLL_STATUSES
    workflows = set(f['workflows']) or {w for w, _ in WORKFLOW_CHOICES}
    # Shift and contract exist only on Daily Crew sheets. Setting either one
    # narrows the search to Daily Crew.
    if f['shift'] or f['contract']:
        workflows &= {'ops'}

    date_from, date_to = f['date_from'], f['date_to']
    q = f['q']
    rows = []

    # Maintenance personal sheets
    if 'maintenance' in workflows:
        qs = MainHeader.objects.filter(_status_filter_for_headers(statuses))
        if q:
            qs = qs.filter(_person_q(q, 'employeeid__'))
        if f['dept']:
            qs = qs.filter(employeeid__roleid__departmentid=f['dept'])
        if f['crew']:
            qs = qs.filter(crewid=f['crew'])
        if date_from or date_to:
            entries = MainEntry.objects.all()
            if date_from:
                entries = entries.filter(startdate__gte=date_from)
            if date_to:
                entries = entries.filter(startdate__lte=date_to)
            qs = qs.filter(mainheaderid__in=entries.values('mainheaderid'))
        qs = qs.select_related('employeeid__roleid__departmentid', 'crewid', 'paidby').annotate(
            hours_all=Sum('mainentry__hoursworked'),
            hours_approved=Sum('mainentry__hoursworked', filter=Q(mainentry__linestatus='Approved')),
            date_first=Min('mainentry__startdate'),
            date_last=Max('mainentry__startdate'),
        )
        for h in qs:
            paid = h.paidat is not None
            bucket = _header_bucket(h.overallstatus, paid)
            emp = h.employeeid
            if h.date_first:
                period = (_d(h.date_first) if h.date_first == h.date_last
                          else f"{_d(h.date_first, year=False)} – {_d(h.date_last)}")
            else:
                period = 'No entries yet'
            url, note = None, ''
            if is_admin:
                if bucket != 'draft':
                    url = reverse('system_timesheet_detail', args=['maintenance', h.mainheaderid])
            elif bucket == 'approved':
                url = reverse('payroll_unprocessed_review', args=[emp.roleid.departmentid_id, h.mainheaderid])
            elif h.date_first:
                url = reverse('payroll_processed_maintenance_month',
                              args=[emp.employeeid, h.date_first.year, h.date_first.month])
            rows.append({
                'workflow': 'Maintenance',
                'person': _person_row(emp),
                'period': period,
                'sort_date': h.date_last or h.startedat.date(),
                'sort_id': h.mainheaderid,
                'crew': h.crewid.crewname if h.crewid_id else '',
                'hours': None if bucket == 'draft' and is_admin else
                         (h.hours_approved if h.overallstatus == 'Completed' else h.hours_all),
                'bucket': bucket,
                'status': _header_label(h.overallstatus, paid),
                'detail': f"Paid {_d(h.paidat)}" if paid else (
                    f"Submitted {_d(h.submittedat)}" if h.submittedat else ''),
                'url': url,
                'note': note,
            })

    # Business personal sheets
    if 'business' in workflows:
        qs = BusinessHeader.objects.filter(_status_filter_for_headers(statuses))
        if q:
            qs = qs.filter(_person_q(q, 'employeeid__'))
        if f['dept']:
            qs = qs.filter(employeeid__roleid__departmentid=f['dept'])
        if f['crew']:
            qs = qs.filter(crewid=f['crew'])
        lo, hi = _month_key_range(date_from, date_to)
        if lo or hi:
            qs = qs.annotate(month_key=F('periodyear') * 100 + F('periodmonth'))
            if lo:
                qs = qs.filter(month_key__gte=lo)
            if hi:
                qs = qs.filter(month_key__lte=hi)
        qs = qs.select_related('employeeid__roleid__departmentid', 'crewid', 'paidby').annotate(
            hours_all=Sum('businessentry__hoursworked'),
            hours_approved=Sum('businessentry__hoursworked', filter=Q(businessentry__linestatus='Approved')),
        )
        for h in qs:
            paid = h.paidat is not None
            bucket = _header_bucket(h.overallstatus, paid)
            emp = h.employeeid
            dept_id = emp.roleid.departmentid_id
            url, note = None, ''
            if is_admin:
                if bucket != 'draft':
                    url = reverse('system_timesheet_detail', args=['business', h.businessheaderid])
            elif bucket == 'approved':
                url = reverse('payroll_business_unprocessed_review', args=[dept_id, h.businessheaderid])
            else:
                url = reverse('payroll_processed_business_month',
                              args=[dept_id, emp.employeeid, h.periodyear, h.periodmonth])
            last_day = calendar.monthrange(h.periodyear, h.periodmonth)[1]
            rows.append({
                'workflow': 'Business',
                'person': _person_row(emp),
                'period': f'{h.get_periodmonth_display()} {h.periodyear}',
                'sort_date': date(h.periodyear, h.periodmonth, last_day),
                'sort_id': h.businessheaderid,
                'crew': h.crewid.crewname if h.crewid_id else '',
                'hours': None if bucket == 'draft' and is_admin else
                         (h.hours_approved if h.overallstatus == 'Completed' else h.hours_all),
                'bucket': bucket,
                'status': _header_label(h.overallstatus, paid),
                'detail': f"Paid {_d(h.paidat)}" if paid else (
                    f"Submitted {_d(h.submittedat)}" if h.submittedat else ''),
                'url': url,
                'note': note,
            })

    # Daily Crew sheets. A sheet matches a person if they are its shifter or
    # have an entry on it.
    if 'ops' in workflows:
        header_statuses = Q(pk__in=[])
        if 'draft' in statuses:
            header_statuses |= Q(overallstatus__in=['Draft', 'Revision Required'])
        if 'submitted' in statuses:
            header_statuses |= Q(overallstatus__in=['Submitted', 'In Progress'])
        if statuses & {'approved', 'paid'}:
            header_statuses |= Q(overallstatus='Completed')
        qs = OperationsHeader.objects.filter(header_statuses)
        if q:
            on_sheet = OperationsEntry.objects.filter(_person_q(q, 'employeeid__')).values('opsheaderid')
            qs = qs.filter(_person_q(q, 'shifterid__') | Q(opsheaderid__in=on_sheet))
        if f['dept']:
            qs = qs.filter(shifterid__roleid__departmentid=f['dept'])
        if f['crew']:
            qs = qs.filter(crewid=f['crew'])
        if f['shift']:
            qs = qs.filter(shifttype=f['shift'])
        if f['contract']:
            qs = qs.filter(opsheaderid__in=OperationsEntry.objects.filter(
                contractid=f['contract']).values('opsheaderid'))
        if date_from:
            qs = qs.filter(shiftdate__gte=date_from)
        if date_to:
            qs = qs.filter(shiftdate__lte=date_to)
        qs = qs.select_related('shifterid__roleid', 'crewid', 'discipline').annotate(
            hours_all=Sum('operationsentry__hoursworked'),
            hours_approved=Sum('operationsentry__hoursworked',
                               filter=Q(operationsentry__linestatus='Approved')),
            people=Count('operationsentry__employeeid', distinct=True),
            unpaid=Count('operationsentry', filter=Q(operationsentry__linestatus='Approved',
                                                     operationsentry__paidat__isnull=True)),
        )
        for h in qs:
            paid = h.overallstatus == 'Completed' and h.unpaid == 0
            bucket = _header_bucket(h.overallstatus, paid)
            if bucket not in statuses:
                continue
            url = None
            if is_admin:
                if bucket != 'draft':
                    url = reverse('system_timesheet_detail', args=['ops', h.opsheaderid])
            elif bucket == 'approved':
                url = reverse('payroll_ops_sheet', args=[h.opsheaderid])
            else:
                d = h.shiftdate
                url = reverse('payroll_ops_daily_shift', args=[d.year, d.month, d.day, h.shifttype])
            person = _person_row(h.shifterid)
            person['role'] = 'Shifter'
            discipline = h.discipline.name if h.discipline_id else (h.section or '')
            rows.append({
                'workflow': 'Daily Crew',
                'person': person,
                'period': f"{_d(h.shiftdate)} · {h.shifttype}",
                'sort_date': h.shiftdate,
                'sort_id': h.opsheaderid,
                'crew': h.crewid.crewname + (f' · {discipline}' if discipline else ''),
                'hours': None if bucket == 'draft' and is_admin else
                         (h.hours_approved if h.overallstatus == 'Completed' else h.hours_all),
                'bucket': bucket,
                'status': _header_label(h.overallstatus, paid),
                'detail': f"{h.people} crew member{'s' if h.people != 1 else ''}",
                'url': url,
                'note': '',
            })

    bonus_statuses = [s for s, b in _BONUS_BUCKETS.items() if b in statuses]

    # Crew (Operations) bonuses: one per employee per month.
    if 'crew_bonus' in workflows and bonus_statuses:
        qs = OperationsBonus.objects.filter(status__in=bonus_statuses)
        if q:
            qs = qs.filter(_person_q(q, 'employeeid__'))
        if f['dept']:
            qs = qs.filter(employeeid__roleid__departmentid=f['dept'])
        if f['crew']:
            qs = qs.filter(employeeid__crewid=f['crew'])
        if date_from:
            qs = qs.filter(bonusmonth__gte=date_from.replace(day=1))
        if date_to:
            qs = qs.filter(bonusmonth__lte=date_to)
        for b in qs.select_related('employeeid__roleid', 'employeeid__crewid', 'appliedbypayroll'):
            url = None
            if not is_admin and b.status == 'Submitted':
                url = reverse('payroll_crew_bonuses_month', args=[b.bonusmonth.year, b.bonusmonth.month])
            elif not is_admin:
                # Applied: shown on the member's month page under Crew → Members.
                url = reverse('payroll_ops_member_month',
                              args=[b.employeeid.employeeid, b.bonusmonth.year, b.bonusmonth.month])
            rows.append({
                'workflow': 'Crew Bonus',
                'person': _person_row(b.employeeid),
                'period': f'{b.bonusmonth:%B %Y}',
                'sort_date': b.bonusmonth,
                'sort_id': b.opsbonusid,
                'crew': b.employeeid.crewid.crewname if b.employeeid.crewid_id else '',
                'hours': None,
                'bucket': _BONUS_BUCKETS[b.status],
                'status': _BONUS_LABELS[b.status],
                # Rate is pay information: Payroll only.
                'detail': '' if is_admin else f'Rate {b.bonusratecode}',
                'url': url,
                'note': '',
            })

    # Employee (Year-End / Ad-Hoc) bonuses
    if 'employee_bonus' in workflows and bonus_statuses:
        qs = EmployeeBonus.objects.filter(status__in=bonus_statuses)
        if q:
            qs = qs.filter(_person_q(q, 'employeeid__'))
        if f['dept']:
            qs = qs.filter(employeeid__roleid__departmentid=f['dept'])
        if f['crew']:
            qs = qs.filter(employeeid__crewid=f['crew'])
        if date_from:
            qs = qs.filter(periodend__gte=date_from)
        if date_to:
            qs = qs.filter(periodstart__lte=date_to)
        for b in qs.select_related('employeeid__roleid', 'employeeid__crewid'):
            url = None
            if not is_admin:
                url = reverse('payroll_employee_bonuses_dept', args=[b.employeeid.roleid.departmentid_id])
                if b.status == 'Applied':
                    url += '?view=applied'
            rows.append({
                'workflow': 'Employee Bonus',
                'person': _person_row(b.employeeid),
                'period': f"{_d(b.periodstart)} – {_d(b.periodend)}",
                'sort_date': b.periodend,
                'sort_id': b.employeebonusid,
                'crew': b.employeeid.crewid.crewname if b.employeeid.crewid_id else '',
                'hours': None,
                'bucket': _BONUS_BUCKETS[b.status],
                'status': _BONUS_LABELS[b.status],
                'detail': b.bonustype if is_admin else f'{b.bonustype} · Rate {b.bonusratecode}',
                'url': url,
                'note': '',
            })

    rows.sort(key=lambda r: (r['sort_date'], r['sort_id']), reverse=True)
    return rows


def _int_or_none(raw):
    return int(raw) if raw and raw.isdigit() else None


@login_required(login_url='login')
def timesheet_search(request):
    if request.user.access_level not in (SYSADMIN, PAYROLL):
        return redirect('profile')
    is_admin = request.user.access_level == SYSADMIN

    status_choices = STATUS_CHOICES if is_admin else [c for c in STATUS_CHOICES if c[0] in PAYROLL_STATUSES]
    valid_statuses = {s for s, _ in status_choices}
    valid_workflows = {w for w, _ in WORKFLOW_CHOICES}

    f = {
        'q': request.GET.get('q', '').strip(),
        'date_from': _parse_date(request.GET.get('date_from', '').strip()),
        'date_to': _parse_date(request.GET.get('date_to', '').strip()),
        'crew': _int_or_none(request.GET.get('crew', '')),
        'workflows': [w for w in request.GET.getlist('workflow') if w in valid_workflows],
        'dept': _int_or_none(request.GET.get('dept', '')),
        'statuses': [s for s in request.GET.getlist('status') if s in valid_statuses] or list(valid_statuses),
        'shift': request.GET.get('shift', '') if request.GET.get('shift') in ('Day', 'Night') else '',
        'contract': _int_or_none(request.GET.get('contract', '')),
    }
    status_given = bool(request.GET.getlist('status'))

    rows = _search(request.user, f)
    page_obj = Paginator(rows, 50).get_page(request.GET.get('page'))
    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'timesheets/timesheet_search.html', {
        'is_admin': is_admin,
        'page_obj': page_obj,
        'f': f,
        'selected_statuses': f['statuses'] if status_given else [],
        'workflow_choices': WORKFLOW_CHOICES,
        'status_choices': status_choices,
        'departments': Department.objects.filter(isactive=1).order_by('departmentname'),
        'crews': Crews.objects.filter(isactive=1).order_by('crewname'),
        'contracts': Contract.objects.order_by('contractcode'),
        'any_filter': any([f['q'], f['date_from'], f['date_to'], f['crew'], f['workflows'],
                           f['dept'], status_given, f['shift'], f['contract']]),
        'querystring': querystring.urlencode(),
    })


_DETAIL_SOURCES = {
    'maintenance': (MainHeader, 'mainheaderid', 'MainHeader'),
    'business': (BusinessHeader, 'businessheaderid', 'BusinessHeader'),
    'ops': (OperationsHeader, 'opsheaderid', 'OperationsHeader'),
}


@login_required(login_url='login')
def system_timesheet_detail(request, kind, pk):
    """System Admin's read-only view of one submitted/approved/paid sheet.
    Drafts are refused. Every open is written to the Audit Log."""
    if request.user.access_level != SYSADMIN:
        return redirect('profile')
    if kind not in _DETAIL_SOURCES:
        return redirect('timesheet_search')
    model, pk_field, table = _DETAIL_SOURCES[kind]
    header = get_object_or_404(model, **{pk_field: pk})

    if _HEADER_BUCKETS.get(header.overallstatus) == 'draft' or (
            header.overallstatus not in _HEADER_BUCKETS and header.overallstatus != 'Completed'):
        messages.error(request, "This timesheet is still a draft with the employee, so its contents can't be viewed.")
        return redirect('timesheet_search')

    log_action(request.user, 'Viewed', table, pk, new_values={'by': 'System Admin', 'view': 'read-only'})

    stat_dates, stat_labels = _stat_info()
    ctx = {'kind': kind, 'header': header, 'stat_dates': stat_dates, 'stat_labels': stat_labels}

    if kind == 'ops':
        entries = OperationsEntry.objects.filter(opsheaderid=header).select_related(
            'employeeid', 'contractid', 'accountid', 'opscategoryid', 'leavetypeid',
            'paidby', 'approvedby_capt',
        ).order_by('employeeid__lastname', 'employeeid__firstname')
        ctx.update({
            'entries': entries,
            'total_hours': sum((e.hoursworked for e in entries), 0),
            'is_stat': header.shiftdate in stat_dates,
            'stat_label': stat_labels.get(header.shiftdate, ''),
            'all_paid': header.overallstatus == 'Completed' and not entries.filter(
                linestatus='Approved', paidat__isnull=True).exists(),
        })
    else:
        if kind == 'maintenance':
            entries = MainEntry.objects.filter(mainheaderid=header).select_related(
                'workcategoryid', 'leavetypeid', 'approvedby').order_by('startdate')
            cat_field, date_field = 'workcategoryid', 'startdate'
        else:
            entries = BusinessEntry.objects.filter(businessheaderid=header).select_related(
                'businesscategoryid', 'leavetypeid', 'approvedby').order_by('dateworked')
            cat_field, date_field = 'businesscategoryid', 'dateworked'
        # Approved sheets: count only approved lines, as every other review
        # page does. Sheets still under review: count everything on them.
        counted = entries.filter(linestatus='Approved') if header.overallstatus == 'Completed' else entries
        payable, non_payable, total = _payable_hours_split(counted, cat_field)
        regular, stat_worked, overtime = _worked_hours_breakdown(counted, cat_field, date_field, stat_dates)
        ctx.update({
            'entries': entries,
            'employee': header.employeeid,
            'date_field': date_field,
            'total_hours': total,
            'payable_hours': payable,
            'non_payable_hours': non_payable,
            'regular_hours': regular,
            'stat_worked_hours': stat_worked,
            'overtime_hours': overtime,
        })
    return render(request, 'timesheets/system_timesheet_detail.html', ctx)
