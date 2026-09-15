from django.core.management.base import BaseCommand

from timesheets.models import MinerLevel

LEVELS = ['Lead', '1', '2', '3', '4']


class Command(BaseCommand):
    help = 'Seed the MinerLevel rows (Lead/1/2/3/4) used to classify which levels a Contract applies to'

    def handle(self, *args, **options):
        created = 0
        for order, code in enumerate(LEVELS):
            _, was_created = MinerLevel.objects.get_or_create(levelcode=code, defaults={'sortorder': order})
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'Seeded {created} new MinerLevel row(s) ({len(LEVELS)} total expected).'))
