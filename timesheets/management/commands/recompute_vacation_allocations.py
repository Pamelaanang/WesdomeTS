import datetime

from django.core.management.base import BaseCommand

from timesheets.leave import get_or_create_vacation_allocation
from users.models import User


class Command(BaseCommand):
    help = 'Pre-warm the vacation allocation for every active employee for a given year (optional — allocations also compute lazily on first access)'

    def add_arguments(self, parser):
        parser.add_argument(
            'year',
            nargs='?',
            type=int,
            default=datetime.date.today().year,
            help='Year to compute allocations for (defaults to current year)',
        )

    def handle(self, *args, **options):
        year = options['year']
        computed = 0
        skipped = 0

        for employee in User.objects.filter(isactive=True):
            allocation = get_or_create_vacation_allocation(employee, year)
            if allocation is not None:
                computed += 1
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'Vacation allocations for {year}: {computed} computed, {skipped} skipped (no hiredate/rate yet).'
        ))
