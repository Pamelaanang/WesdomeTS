from django.db import migrations, models


def seed_disciplinary(apps, schema_editor):
    # The two disciplinary options on the crew daily sheet:
    #  - Disciplinary Action: a paid shift, no crew bonus on those hours
    #    (an ops work category, so it still counts as worked, paid time).
    #  - Disciplinary Suspension: no pay (an unpaid leave type, so it lands in
    #    non-payable hours and never counts as worked time).
    Opscategory = apps.get_model('timesheets', 'Opscategory')
    LeaveType = apps.get_model('timesheets', 'LeaveType')
    Opscategory.objects.update_or_create(
        categoryname='Disciplinary Action',
        defaults={'isproductive': 0, 'isactive': 1, 'ispayable': True,
                  'isovertime': False, 'isdisciplinary': True},
    )
    LeaveType.objects.update_or_create(
        leavetypename='Disciplinary Suspension',
        defaults={'isactive': 1, 'ispayable': False, 'isdisciplinary': True},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0045_category_isovertime'),
    ]

    operations = [
        migrations.AddField(
            model_name='opscategory',
            name='isdisciplinary',
            field=models.BooleanField(db_column='IsDisciplinary', default=False),
        ),
        migrations.AddField(
            model_name='leavetype',
            name='isdisciplinary',
            field=models.BooleanField(db_column='IsDisciplinary', default=False),
        ),
        migrations.RunPython(seed_disciplinary, migrations.RunPython.noop),
    ]
