# Part of the surrogate-key migration: switching User's primary key from the
# human-editable EmployeeID (varchar) to a new auto-incrementing EID.
#
# Every one of these tables is currently empty, and every one of them has at
# least one foreign key column pointing at User (Employee.EmployeeID). Rather
# than hand-writing precise ALTER TABLE / DROP+ADD CONSTRAINT SQL for each of
# those columns individually, we drop these (empty) tables here and recreate
# them fresh in a later migration once User's PK has changed — Django will
# then generate them correctly typed against the new EID column automatically,
# since none of their ForeignKey(User, ...) fields specify an explicit
# to_field and so always target whatever User's current primary key is.
#
# Dropped in child-before-parent order within this app.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("timesheets", "0027_statholiday_province_businessentry_dateworked"),
        ("users", "0008_user_accountid_user_contractid_user_employmenttype"),
    ]

    operations = [
        migrations.DeleteModel(name="OperationsEntry"),
        migrations.DeleteModel(name="OperationsHeader"),
        migrations.DeleteModel(name="MainEntry"),
        migrations.DeleteModel(name="MainHeader"),
        migrations.DeleteModel(name="BusinessEntry"),
        migrations.DeleteModel(name="BusinessHeader"),
        migrations.DeleteModel(name="EmployeeBonus"),
        migrations.DeleteModel(name="OperationsBonus"),
        migrations.DeleteModel(name="Auditlog"),
        migrations.DeleteModel(name="LeaveAllocation"),
    ]
