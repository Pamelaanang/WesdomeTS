from django.core.management.base import BaseCommand
from django.db import connection


RENAMES = {
    'EMP001': 'EMP001U',
    'EMP002': 'EMP002Supv',
    'EMP003': 'EMP003Sys',
    'EMP004': 'EMP004Pay',
    'EMP005': 'EMP005Cap',
    'EMP006': 'EMP006SupI',
    'EMP007': 'EMP007Shift',
    'EMP008': 'EMP008Min',
}

# Every table + column that stores an EmployeeID value (child tables only, not the PK itself)
CHILD_COLUMNS = [
    ('Employee',          'SupervisorID'),
    ('AuditLog',         'EmployeeID'),
    ('LeaveAllocation',  'EmployeeID'),
    ('CrewAssignment',   'ShifterID'),
    ('CrewAssignment',   'EmployeeID'),
    ('MainHeader',       'EmployeeID'),
    ('MainHeader',       'PaidBy'),
    ('MainEntry',        'ApprovedBy'),
    ('BusinessHeader',   'EmployeeID'),
    ('BusinessHeader',   'PaidBy'),
    ('BusinessEntry',    'ApprovedBy'),
    ('OperationsHeader', 'ShifterID'),
    ('OperationsHeader', 'OpsHApprovedBy_Capt'),
    ('OperationsHeader', 'OpsHApprovedBy_Sup'),
    ('OperationsEntry',  'EmployeeID'),
    ('OperationsEntry',  'PaidBy'),
    ('OperationsEntry',  'ApprovedBy_Capt'),
    ('OperationsEntry',  'ApprovedBy_Sup'),
]


class Command(BaseCommand):
    help = 'Rename employee IDs with role-based suffixes across all tables'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be changed without touching the database',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no changes will be made\n'))
            for old, new in RENAMES.items():
                self.stdout.write(f'  {old} → {new}')
            return

        self.stdout.write('Starting employee ID rename...')

        with connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS = 0')

            for old_id, new_id in RENAMES.items():
                self.stdout.write(f'  Renaming {old_id} → {new_id}')

                # Update all child columns first
                for table, column in CHILD_COLUMNS:
                    cursor.execute(
                        f'UPDATE `{table}` SET `{column}` = %s WHERE `{column}` = %s',
                        [new_id, old_id]
                    )

                # Update the primary key last
                cursor.execute(
                    'UPDATE `Employee` SET `EmployeeID` = %s WHERE `EmployeeID` = %s',
                    [new_id, old_id]
                )

            cursor.execute('SET FOREIGN_KEY_CHECKS = 1')

        self.stdout.write(self.style.SUCCESS('Done. All employee IDs renamed successfully.'))
