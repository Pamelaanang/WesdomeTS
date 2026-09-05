# Part of the surrogate-key migration (see timesheets/migrations/0028 for the
# full rationale). Both tables are empty. CrewCoverage could not be dropped
# until timesheets 0028 removed OperationsHeader, which referenced it.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_user_accountid_user_contractid_user_employmenttype"),
        ("timesheets", "0028_drop_employee_referencing_tables"),
    ]

    operations = [
        migrations.DeleteModel(name="CrewAssignment"),
        migrations.DeleteModel(name="CrewCoverage"),
    ]
