from django.db import migrations, models
import django.db.models.deletion


def copy_text_to_fk(apps, schema_editor):
    User = apps.get_model('users', 'User')
    MinerLevel = apps.get_model('timesheets', 'MinerLevel')
    levels = {level.levelcode: level for level in MinerLevel.objects.all()}
    for user in User.objects.exclude(minerlevel__isnull=True).exclude(minerlevel=''):
        level = levels.get(user.minerlevel)
        if level is None:
            print(f'\n  minerlevel {user.minerlevel!r} on {user.employeeid} has no MinerLevel row; left unset')
            continue
        user.minerlevel_fk = level
        user.save(update_fields=['minerlevel_fk'])


def copy_fk_to_text(apps, schema_editor):
    User = apps.get_model('users', 'User')
    for user in User.objects.exclude(minerlevel_fk__isnull=True).select_related('minerlevel_fk'):
        user.minerlevel = user.minerlevel_fk.levelcode
        user.save(update_fields=['minerlevel'])


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0028_remove_miner_seat'),
        ('timesheets', '0036_minerlevel_staff'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='minerlevel_fk',
            field=models.ForeignKey(
                blank=True, null=True, db_column='MinerLevelID',
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='users', to='timesheets.minerlevel',
            ),
        ),
        migrations.RunPython(copy_text_to_fk, copy_fk_to_text),
        migrations.RemoveField(
            model_name='user',
            name='minerlevel',
        ),
        migrations.RenameField(
            model_name='user',
            old_name='minerlevel_fk',
            new_name='minerlevel',
        ),
    ]
