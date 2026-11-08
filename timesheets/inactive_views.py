"""Payroll: Inactive Employees. Departments, then a card for each inactive
person, linking into the existing Processed history pages (which load for
inactive employees too)."""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404, redirect, render

from users.models import Department, User
from .models import BusinessHeader, MainHeader, OperationsEntry

PAYROLL = 7


@login_required(login_url='login')
def payroll_inactive(request):
    if request.user.access_level != PAYROLL:
        return redirect('profile')
    departments = Department.objects.annotate(
        inactive_count=Count('roles__user', distinct=True, filter=Q(roles__user__isactive=False) & (
            Q(roles__user__onboarding_status__isnull=True) | Q(roles__user__onboarding_status='activated'))),
    ).filter(inactive_count__gt=0).order_by('departmentname')
    return render(request, 'timesheets/payroll_inactive.html', {'departments': departments})


def _inactive_people(dept_id):
    """Inactive employees of a department. Leaves out hires that never started
    (pending or rejected at IT onboarding): they have no pay history."""
    return User.objects.filter(roleid__departmentid=dept_id, isactive=False).filter(
        Q(onboarding_status__isnull=True) | Q(onboarding_status='activated')
    )


@login_required(login_url='login')
def payroll_inactive_dept(request, dept_id):
    if request.user.access_level != PAYROLL:
        return redirect('profile')
    dept = get_object_or_404(Department, departmentid=dept_id)
    people = _inactive_people(dept_id).select_related('roleid').annotate(
        has_maintenance=Exists(MainHeader.objects.filter(employeeid=OuterRef('pk'), paidat__isnull=False)),
        has_business=Exists(BusinessHeader.objects.filter(employeeid=OuterRef('pk'), paidat__isnull=False)),
        has_crew=Exists(OperationsEntry.objects.filter(employeeid=OuterRef('pk'), linestatus='Approved')),
        unpaid_personal=Count('mainheader', filter=Q(mainheader__overallstatus='Completed', mainheader__paidat__isnull=True), distinct=True)
        + Count('businessheader', filter=Q(businessheader__overallstatus='Completed', businessheader__paidat__isnull=True), distinct=True),
        unpaid_crew=Count('operationsentry', filter=Q(operationsentry__linestatus='Approved', operationsentry__paidat__isnull=True), distinct=True),
    ).order_by('-terminationdate', 'lastname', 'firstname')
    return render(request, 'timesheets/payroll_inactive_dept.html', {'dept': dept, 'people': people})
