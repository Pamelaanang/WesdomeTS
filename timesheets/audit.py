from django.utils import timezone

from .models import Auditlog


def log_action(user, action, table_name, record_id, old_values=None, new_values=None):
    """Record one audit-log entry. old_values/new_values should only include
    the fields that actually changed, e.g. {'overallstatus': 'Draft'} -> {'overallstatus': 'Submitted'}."""
    Auditlog.objects.create(
        employeeid=user,
        action=action,
        tablename=table_name,
        recordid=record_id,
        oldvalue=old_values,
        newvalue=new_values,
        timestamp=timezone.now(),
    )
