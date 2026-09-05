# The actual surrogate-key swap. EID becomes the new primary key; EmployeeID
# becomes a plain unique, editable field. Unlike the tables dropped in 0009,
# Employee itself can't be dropped and recreated (it holds real rows), so this
# is done as a careful in-place conversion:
#
#  1. Add EID as an auto-incrementing unique column (not yet primary) — MySQL
#     assigns every existing row a fresh integer id here.
#  2. Convert the one self-referencing column, SupervisorID, from a string
#     employeeid reference to an integer EID reference — via a temp column
#     backfilled by joining the old string value to the newly-assigned EID,
#     so the one real relationship in the data (a supervisor link) survives
#     the conversion intact rather than being dropped.
#  3. Promote EID to the primary key; demote EmployeeID to a plain unique key.
#  4. Repoint the three Django-internal tables that also reference
#     Employee.EmployeeID (the auth permission M2M tables and the admin
#     action log) at the new EID column. All three are empty, so this is a
#     straight column-type conversion with no data to preserve.
#
# Uses SeparateDatabaseAndState because the actual SQL has to run in this
# precise order for MySQL to accept it — Django's autodetector doesn't have
# a built-in operation for "swap which field is the primary key while other
# rows reference it", so the database side is hand-written here while the
# state side stays a normal AddField/AlterField pair, matching the previous
# (reverted) migration Django itself proposed.
from django.db import migrations, models


def convert_supervisorid_and_related_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # SupervisorID: back up the existing string values, convert to EID references
        cursor.execute("ALTER TABLE `Employee` ADD COLUMN `SupervisorEID` INT NULL")
        cursor.execute("""
            UPDATE `Employee` e1
            JOIN `Employee` e2 ON e1.`SupervisorID` = e2.`EmployeeID`
            SET e1.`SupervisorEID` = e2.`EID`
        """)
        cursor.execute(
            "ALTER TABLE `Employee` DROP FOREIGN KEY `Employee_SupervisorID_a97d28e4_fk_Employee_EmployeeID`"
        )
        cursor.execute("ALTER TABLE `Employee` DROP COLUMN `SupervisorID`")
        cursor.execute("ALTER TABLE `Employee` CHANGE `SupervisorEID` `SupervisorID` INT NULL")
        cursor.execute("""
            ALTER TABLE `Employee`
            ADD CONSTRAINT `Employee_SupervisorID_eid_fk`
            FOREIGN KEY (`SupervisorID`) REFERENCES `Employee` (`EID`)
        """)

        # The three Django-internal tables — all empty, no backfill needed
        internal_fk_columns = [
            ("Employee_groups", "user_id",
             "Employee_groups_user_id_abc1d9d4_fk_Employee_EmployeeID"),
            ("Employee_user_permissions", "user_id",
             "Employee_user_permis_user_id_876619f1_fk_Employee_"),
            ("django_admin_log", "user_id",
             "django_admin_log_user_id_c564eba6_fk_Employee_EmployeeID"),
        ]
        for table, column, fk_name in internal_fk_columns:
            cursor.execute(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{fk_name}`")
            cursor.execute(f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` INT NULL")
            cursor.execute(f"""
                ALTER TABLE `{table}`
                ADD CONSTRAINT `{table}_{column}_eid_fk`
                FOREIGN KEY (`{column}`) REFERENCES `Employee` (`EID`)
            """)


def reverse_convert(apps, schema_editor):
    raise NotImplementedError(
        "This migration is not reversible — restore from the pre-migration "
        "backup in downloads/ instead."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_drop_crew_tables_for_pk_swap"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE `Employee` ADD COLUMN `EID` INT NOT NULL AUTO_INCREMENT UNIQUE",
                    reverse_sql=migrations.RunSQL.noop,
                ),
                migrations.RunPython(convert_supervisorid_and_related_tables, reverse_convert),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE `Employee` "
                        "DROP PRIMARY KEY, "
                        "ADD PRIMARY KEY (`EID`), "
                        "ADD UNIQUE KEY `Employee_EmployeeID_uniq` (`EmployeeID`)"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="user",
                    name="eid",
                    field=models.AutoField(db_column="EID", primary_key=True, serialize=False),
                ),
                migrations.AlterField(
                    model_name="user",
                    name="employeeid",
                    field=models.CharField(db_column="EmployeeID", max_length=255, unique=True),
                ),
                migrations.AlterField(
                    model_name="user",
                    name="supervisorid",
                    field=models.ForeignKey(
                        blank=True, null=True, on_delete=models.deletion.DO_NOTHING,
                        db_column="SupervisorID", to="users.user",
                    ),
                ),
            ],
        ),
    ]
