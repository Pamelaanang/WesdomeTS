from django.db import migrations, models


def add_staff_level(apps, schema_editor):
    MinerLevel = apps.get_model('timesheets', 'MinerLevel')
    MinerLevel.objects.get_or_create(levelcode='Staff', defaults={'sortorder': -1})


def remove_staff_level(apps, schema_editor):
    MinerLevel = apps.get_model('timesheets', 'MinerLevel')
    MinerLevel.objects.filter(levelcode='Staff', contracts__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0035_minerlevel_contract_levels'),
    ]

    operations = [
        migrations.AlterField(
            model_name='minerlevel',
            name='levelcode',
            field=models.CharField(db_column='LevelCode', max_length=10, unique=True),
        ),
        migrations.RunPython(add_staff_level, remove_staff_level),
    ]
