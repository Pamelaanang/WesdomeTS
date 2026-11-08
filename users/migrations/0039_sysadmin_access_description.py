from django.db import migrations

NEW = (
    'Manages system users, roles, and settings. Can view submitted, approved and paid '
    'timesheets across all departments, read-only, and every timesheet opened is recorded '
    'in the Audit Log. Sees that drafts exist but not their contents, and sees bonus status '
    'but not bonus rates. Does not submit personal timesheets.'
)
OLD = (
    'Manages system users, roles, and settings. Has full visibility across all timesheets, '
    'departments, and reports. Does not submit personal timesheets.'
)


def forwards(apps, schema_editor):
    apps.get_model('users', 'Accesslevel').objects.filter(accessid=1).update(accessdescription=NEW)


def backwards(apps, schema_editor):
    apps.get_model('users', 'Accesslevel').objects.filter(accessid=1).update(accessdescription=OLD)


class Migration(migrations.Migration):
    dependencies = [('users', '0038_drop_grid_cell_and_routing')]
    operations = [migrations.RunPython(forwards, backwards)]
