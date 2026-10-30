from django.db import migrations, models


def fill_basket_keys(apps, schema_editor):
    User = apps.get_model('users', 'User')
    BasketLead = apps.get_model('users', 'BasketLead')
    for u in User.objects.filter(roleid__accessid__accessid=5, crewid__isnull=False).exclude(shiftertype__isnull=True):
        if u.isactive or u.onboarding_status == 'pending':
            u.basket_key = f'{u.crewid_id}:{u.shiftertype}'
            u.save(update_fields=['basket_key'])
    for lead in BasketLead.objects.filter(enddate__isnull=True):
        lead.basket_key = f'{lead.crewid_id}:{lead.shiftertype}'
        lead.save(update_fields=['basket_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0029_user_minerlevel_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='basket_key',
            field=models.CharField(blank=True, db_column='BasketKey', editable=False, max_length=20, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='basketlead',
            name='basket_key',
            field=models.CharField(blank=True, db_column='BasketKey', editable=False, max_length=20, null=True, unique=True),
        ),
        migrations.RunPython(fill_basket_keys, migrations.RunPython.noop),
    ]
