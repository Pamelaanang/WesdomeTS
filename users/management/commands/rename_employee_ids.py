from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = (
        'Rename an employee\'s EmployeeID. Now that every table references the '
        'stable EID surrogate key rather than EmployeeID directly, this is a '
        'single-row update — no cascading through other tables is needed.'
    )

    def add_arguments(self, parser):
        parser.add_argument('old_id', help='Current EmployeeID')
        parser.add_argument('new_id', help='New EmployeeID')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be changed without touching the database',
        )

    def handle(self, *args, **options):
        old_id = options['old_id']
        new_id = options['new_id']
        dry_run = options['dry_run']

        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM `Employee` WHERE `EmployeeID` = %s', [old_id])
            if cursor.fetchone()[0] == 0:
                raise CommandError(f"No employee found with EmployeeID '{old_id}'.")

            cursor.execute('SELECT COUNT(*) FROM `Employee` WHERE `EmployeeID` = %s', [new_id])
            if cursor.fetchone()[0] > 0:
                raise CommandError(f"EmployeeID '{new_id}' is already in use.")

        if dry_run:
            self.stdout.write(self.style.WARNING(f'DRY RUN — would rename {old_id} -> {new_id}. No changes made.'))
            return

        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE `Employee` SET `EmployeeID` = %s WHERE `EmployeeID` = %s',
                [new_id, old_id],
            )

        self.stdout.write(self.style.SUCCESS(f'Done. {old_id} renamed to {new_id}.'))
