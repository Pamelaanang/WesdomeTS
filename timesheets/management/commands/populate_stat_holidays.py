import datetime
import holidays
from django.core.management.base import BaseCommand
from timesheets.models import StatHoliday

PROVINCES = ['ON', 'QC']


def _first_monday(year, month):
    """Return the date of the first Monday of a given month."""
    d = datetime.date(year, month, 1)
    days_until_monday = (7 - d.weekday()) % 7
    return d + datetime.timedelta(days=days_until_monday)


# Extra holidays not covered by the holidays library, keyed by (province, name).
# Each value is a callable that takes a year and returns a date.
CUSTOM_HOLIDAYS = [
    ('ON', 'Civic Holiday (Simcoe Day)', lambda y: _first_monday(y, 8)),
]


class Command(BaseCommand):
    help = 'Populate StatHoliday table with Ontario + Quebec statutory holidays for a given year'

    def add_arguments(self, parser):
        parser.add_argument(
            'year',
            nargs='?',
            type=int,
            default=datetime.date.today().year,
            help='Year to populate (defaults to current year)',
        )

    def handle(self, *args, **options):
        year = options['year']
        created = 0
        skipped = 0

        # Library-sourced holidays
        for prov in PROVINCES:
            prov_holidays = holidays.Canada(prov=prov, years=year)
            for stat_date, name in sorted(prov_holidays.items()):
                _, was_created = StatHoliday.objects.get_or_create(
                    statdate=stat_date,
                    province=prov,
                    defaults={'statname': name},
                )
                if was_created:
                    created += 1
                    self.stdout.write(f'  [{prov}] {stat_date} — {name}')
                else:
                    skipped += 1

        # Custom holidays not in the library
        for prov, name, date_fn in CUSTOM_HOLIDAYS:
            stat_date = date_fn(year)
            _, was_created = StatHoliday.objects.get_or_create(
                statdate=stat_date,
                province=prov,
                defaults={'statname': name},
            )
            if was_created:
                created += 1
                self.stdout.write(f'  [{prov}] {stat_date} — {name}')
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done: {created} added, {skipped} already existed for {year}'
        ))
