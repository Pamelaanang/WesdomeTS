from django.apps import AppConfig


class TimesheetsConfig(AppConfig):
    name = 'timesheets'

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_save, pre_save

        from .models import sync_basket, sync_basket_lead, sync_discipline, sync_user_home

        # Every record that stores a discipline gets its link set on save.
        for label in (
            'users.User', 'users.Position', 'users.CrewCoverage',
            'users.CrewAssignment', 'users.BasketLead', 'timesheets.OperationsHeader',
        ):
            pre_save.connect(sync_discipline, sender=apps.get_model(label), dispatch_uid=f'sync_discipline_{label}')
        for label in ('users.CrewAssignment', 'users.CrewCoverage', 'users.BasketLead'):
            pre_save.connect(sync_basket, sender=apps.get_model(label), dispatch_uid=f'sync_basket_{label}')

        # Shifter homes and second-basket leads feed the basket table.
        post_save.connect(sync_user_home, sender=apps.get_model('users.User'), dispatch_uid='sync_user_home')
        post_save.connect(sync_basket_lead, sender=apps.get_model('users.BasketLead'), dispatch_uid='sync_basket_lead')
