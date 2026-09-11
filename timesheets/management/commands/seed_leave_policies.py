import datetime

from django.core.management.base import BaseCommand

from timesheets.models import LeaveType, VacationRatePolicy

INITIAL_RATES = {
    'ops_development': 12,
    'ops_other': 10,
    'non_operations': 12,
}


class Command(BaseCommand):
    help = 'Seed the Lieu Day / Unpaid Leave LeaveType rows and the initial VacationRatePolicy rates for a given year'

    def add_arguments(self, parser):
        parser.add_argument(
            'year',
            nargs='?',
            type=int,
            default=datetime.date.today().year,
            help='Year to seed vacation rates for (defaults to current year)',
        )

    def handle(self, *args, **options):
        year = options['year']
        created = 0

        for name in ('Lieu Day', 'Unpaid Leave'):
            _, was_created = LeaveType.objects.get_or_create(
                leavetypename=name, defaults={'isactive': 1},
            )
            if was_created:
                created += 1

        for bucket, rate in INITIAL_RATES.items():
            _, was_created = VacationRatePolicy.objects.get_or_create(
                bucket=bucket, effective_year=year, defaults={'monthly_rate_hours': rate},
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'Seeded leave data for {year}: {created} row(s) created.'))
