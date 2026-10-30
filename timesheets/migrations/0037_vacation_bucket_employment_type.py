from django.db import migrations, models


RENAMES = {'ops_development': 'ops_staff', 'ops_other': 'ops_contract'}


def rename_buckets_and_reset_ops_allocations(apps, schema_editor):
    VacationRatePolicy = apps.get_model('timesheets', 'VacationRatePolicy')
    LeaveAllocation = apps.get_model('timesheets', 'LeaveAllocation')
    LeaveType = apps.get_model('timesheets', 'LeaveType')

    for old, new in RENAMES.items():
        VacationRatePolicy.objects.filter(bucket=old).update(bucket=new)

    # Operations vacation allocations were calculated from discipline. Clear
    # them so they're recalculated from employment type the next time they're
    # needed. Leave is counted from entries, not from these rows, so nothing
    # else points at them.
    vacation_type = LeaveType.objects.filter(leavetypename='Regular Vacation').first()
    if vacation_type:
        LeaveAllocation.objects.filter(
            leavetypeid=vacation_type,
            employeeid__roleid__accessid__accessid__in=[5, 8],
        ).delete()


def restore_buckets(apps, schema_editor):
    VacationRatePolicy = apps.get_model('timesheets', 'VacationRatePolicy')
    for old, new in RENAMES.items():
        VacationRatePolicy.objects.filter(bucket=new).update(bucket=old)


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0036_minerlevel_staff'),
        ('users', '0030_basket_key'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vacationratepolicy',
            name='bucket',
            field=models.CharField(choices=[('ops_staff', 'Operations - Staff'), ('ops_contract', 'Operations - Contract'), ('non_operations', 'Non-Operations (Business/Maintenance)')], db_column='Bucket', max_length=20),
        ),
        migrations.RunPython(rename_buckets_and_reset_ops_allocations, restore_buckets),
    ]
