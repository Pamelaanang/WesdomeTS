from django.core.management.base import BaseCommand

from users.models import Roles


class Command(BaseCommand):
    help = (
        'Seed the Spare Shifter role — a temporary role a Miner is flipped into while '
        'covering a crew, mirroring Shift Coordinator on department/access level (al=5) '
        'so it participates in the same Shifter-scoped dropdowns and gates.'
    )

    def handle(self, *args, **options):
        shift_coordinator = Roles.objects.filter(rolename='Shift Coordinator').first()
        if not shift_coordinator:
            self.stderr.write(self.style.ERROR(
                'Shift Coordinator role not found — cannot derive department/access level for Spare Shifter.'
            ))
            return

        role, created = Roles.objects.get_or_create(
            rolename='Spare Shifter',
            defaults={
                'departmentid': shift_coordinator.departmentid,
                'accessid': shift_coordinator.accessid,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Spare Shifter role (roleid={role.roleid}).'))
        else:
            self.stdout.write('Spare Shifter role already exists.')
