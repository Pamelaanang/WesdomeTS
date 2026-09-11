from django.db.models import Q, Sum
from django.utils import timezone

from users.models import CrewAssignment

from .audit import log_action
from .models import (
    BusinessEntry, LeaveAllocation, LeaveType, LieuDayLedger, MainEntry,
    OperationsEntry, StatHoliday, VacationRatePolicy,
)

VACATION_TYPE_NAME = 'Regular Vacation'
FLOATER_TYPE_NAME = 'Floater'
LIEU_DAY_TYPE_NAME = 'Lieu Day'
UNPAID_LEAVE_TYPE_NAME = 'Unpaid Leave'

# Access levels that file their own hours via BusinessEntry (Supervisor, Mine
# Captain, Shifter, Business Employee) — the only ones salaried enough to
# accrue lieu days. Operations crew members (8) and Maintenance Crew (9) are
# hourly and never accrue or use them.
LIEU_ELIGIBLE_ACCESS_LEVELS = (3, 4, 5, 6)


def get_leave_type(name):
    return LeaveType.objects.filter(leavetypename=name, isactive=1).first()


def leave_type_ids_context():
    """{'vacation_leavetype_id': ..., 'floater_leavetype_id': ..., 'lieu_leavetype_id': ...}
    for templates that need to compare a category_selection value against these by id."""
    vacation_type = get_leave_type(VACATION_TYPE_NAME)
    floater_type = get_leave_type(FLOATER_TYPE_NAME)
    lieu_type = get_leave_type(LIEU_DAY_TYPE_NAME)
    return {
        'vacation_leavetype_id': vacation_type.leavetypeid if vacation_type else None,
        'floater_leavetype_id': floater_type.leavetypeid if floater_type else None,
        'lieu_leavetype_id': lieu_type.leavetypeid if lieu_type else None,
    }


def is_lieu_eligible(employee):
    return employee.access_level in LIEU_ELIGIBLE_ACCESS_LEVELS


def get_operations_employee_type(employee, as_of=None):
    """A Shifter uses their own shiftertype; a crew member uses the
    shiftertype of the Shifter they're currently assigned under."""
    if employee.shiftertype:
        return employee.shiftertype

    as_of = as_of or timezone.now().date()
    assignment = (
        CrewAssignment.objects
        .filter(employee=employee, startdate__lte=as_of)
        .filter(Q(enddate__isnull=True) | Q(enddate__gte=as_of))
        .select_related('shifter')
        .order_by('-startdate')
        .first()
    )
    return assignment.shifter.shiftertype if assignment and assignment.shifter else None


def get_vacation_bucket(employee):
    if employee.access_level in (5, 8):
        optype = get_operations_employee_type(employee)
        return 'ops_development' if optype == 'Development' else 'ops_other'
    return 'non_operations'


def get_monthly_vacation_rate(bucket, year):
    row = (
        VacationRatePolicy.objects
        .filter(bucket=bucket, effective_year__lte=year)
        .order_by('-effective_year')
        .first()
    )
    return row.monthly_rate_hours if row else None


def get_or_create_vacation_allocation(employee, year):
    """Returns this employee's Vacation LeaveAllocation for `year`, computing
    and creating it (hire-year prorated, or full 12 months) on first access.
    Returns None (never raises) if hiredate or a rate isn't set up yet."""
    vacation_type = get_leave_type(VACATION_TYPE_NAME)
    if not vacation_type:
        return None

    row = LeaveAllocation.objects.filter(
        employeeid=employee, leavetypeid=vacation_type, year=year,
    ).first()
    if row:
        return row

    if not employee.hiredate or employee.hiredate.year > year:
        return None

    bucket = get_vacation_bucket(employee)
    rate = get_monthly_vacation_rate(bucket, year)
    if rate is None:
        return None

    if employee.hiredate.year == year:
        months = 12 - employee.hiredate.month + 1
        isprorated = 1
    else:
        months = 12
        isprorated = 0

    return LeaveAllocation.objects.create(
        employeeid=employee, leavetypeid=vacation_type, year=year,
        allocatedhours=rate * months, isprorated=isprorated,
    )


def _sum_leave_hours(employee, leave_type, year, statuses, exclude_entry=None):
    """Sum hoursworked for a given LeaveType/employee/year, live across
    whichever of the three entry tables carries it, filtered to linestatus
    in `statuses`. This is the ledger — no separate stored counter."""
    total = 0

    main_qs = MainEntry.objects.filter(
        mainheaderid__employeeid=employee, leavetypeid=leave_type,
        startdate__year=year, linestatus__in=statuses,
    )
    if isinstance(exclude_entry, MainEntry):
        main_qs = main_qs.exclude(pk=exclude_entry.pk)
    total += main_qs.aggregate(total=Sum('hoursworked'))['total'] or 0

    business_qs = BusinessEntry.objects.filter(
        businessheaderid__employeeid=employee, leavetypeid=leave_type,
        dateworked__year=year, linestatus__in=statuses,
    )
    if isinstance(exclude_entry, BusinessEntry):
        business_qs = business_qs.exclude(pk=exclude_entry.pk)
    total += business_qs.aggregate(total=Sum('hoursworked'))['total'] or 0

    ops_qs = OperationsEntry.objects.filter(
        employeeid=employee, leavetypeid=leave_type,
        opsheaderid__shiftdate__year=year, linestatus__in=statuses,
    )
    if isinstance(exclude_entry, OperationsEntry):
        ops_qs = ops_qs.exclude(pk=exclude_entry.pk)
    total += ops_qs.aggregate(total=Sum('hoursworked'))['total'] or 0

    return total


def get_vacation_approved_hours(employee, year, exclude_entry=None):
    vacation_type = get_leave_type(VACATION_TYPE_NAME)
    if not vacation_type:
        return 0
    return _sum_leave_hours(employee, vacation_type, year, ('Approved',), exclude_entry)


def get_vacation_pending_hours(employee, year, exclude_entry=None):
    vacation_type = get_leave_type(VACATION_TYPE_NAME)
    if not vacation_type:
        return 0
    return _sum_leave_hours(employee, vacation_type, year, ('Draft', 'New'), exclude_entry)


def get_vacation_remaining(employee, year):
    allocation = get_or_create_vacation_allocation(employee, year)
    if allocation is None:
        return None
    return allocation.allocatedhours - get_vacation_approved_hours(employee, year)


def validate_vacation_entry(employee, year, hours, exclude_entry=None):
    """Returns an error string if logging `hours` of Vacation would exceed
    the remaining balance (reserving pending requests too, not just
    approved), else None. Never blocks if no allocation is computable yet."""
    allocation = get_or_create_vacation_allocation(employee, year)
    if allocation is None:
        return None

    approved = get_vacation_approved_hours(employee, year, exclude_entry=exclude_entry)
    pending = get_vacation_pending_hours(employee, year, exclude_entry=exclude_entry)
    remaining = allocation.allocatedhours - approved - pending

    if hours > remaining:
        if is_lieu_eligible(employee):
            return (
                f"This would exceed the remaining vacation balance ({remaining} hrs available). "
                f"Log the overage as a separate 'Lieu Day' or 'Unpaid Leave' line instead."
            )
        return (
            f"This would exceed the remaining vacation balance ({remaining} hrs available). "
            f"Log the overage as a separate 'Unpaid Leave' line instead."
        )
    return None


def get_floater_available(employee, year, exclude_entry=None):
    floater_type = get_leave_type(FLOATER_TYPE_NAME)
    if not floater_type:
        return True
    used = _sum_leave_hours(employee, floater_type, year, ('Draft', 'New', 'Approved'), exclude_entry)
    return used == 0


def validate_floater_entry(employee, year, exclude_entry=None):
    if not get_floater_available(employee, year, exclude_entry=exclude_entry):
        return "A floater day has already been used for this year."
    return None


def sync_lieu_ledger_for_employee(employee):
    """For every past stat date with no ledger row yet, bank a Lieu Day if
    this (lieu-eligible) employee logged zero BusinessEntry hours that day.
    One calendar date can only ever bank one lieu day, even if more than one
    active StatHoliday row shares that date (e.g. a holiday observed in both
    Ontario and Quebec). Also self-heals: an unused (Banked) ledger row whose
    holiday was muted after the fact is pruned — a already-Used one is a real
    historical transaction and is left alone."""
    if not is_lieu_eligible(employee):
        return

    LieuDayLedger.objects.filter(
        employeeid=employee, status='Banked', statholidayid__isactive=0,
    ).delete()

    today = timezone.now().date()
    existing_dates = set(
        LieuDayLedger.objects.filter(employeeid=employee).values_list('statholidayid__statdate', flat=True)
    )
    stat_holidays = StatHoliday.objects.filter(
        isactive=1, statdate__lt=today,
    ).exclude(statdate__in=existing_dates).order_by('statdate')

    for sh in stat_holidays:
        if sh.statdate in existing_dates:
            continue  # already banked against another province's row for this date, this run
        worked = (
            BusinessEntry.objects
            .filter(businessheaderid__employeeid=employee, dateworked=sh.statdate)
            .exclude(linestatus='Rejected')
            .aggregate(total=Sum('hoursworked'))['total'] or 0
        )
        if worked == 0:
            ledger = LieuDayLedger.objects.create(employeeid=employee, statholidayid=sh)
            log_action(
                employee, 'LieuDayBanked', 'LieuDayLedger', ledger.ledgerid,
                new_values={'statdate': str(sh.statdate)},
            )
        existing_dates.add(sh.statdate)


def get_lieu_balance(employee):
    if not is_lieu_eligible(employee):
        return 0
    sync_lieu_ledger_for_employee(employee)
    return LieuDayLedger.objects.filter(employeeid=employee, status='Banked').count()


def consume_lieu_day(employee, entry):
    if not is_lieu_eligible(employee):
        return
    row = LieuDayLedger.objects.filter(employeeid=employee, status='Banked').order_by('earnedat').first()
    if row:
        row.status = 'Used'
        row.usedat = timezone.now()
        row.used_entry_type = type(entry).__name__
        row.used_entry_id = entry.pk
        row.save()
        log_action(
            employee, 'LieuDayUsed', 'LieuDayLedger', row.ledgerid,
            new_values={'used_entry_id': entry.pk},
        )
