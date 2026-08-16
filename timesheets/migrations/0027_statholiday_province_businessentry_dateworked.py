from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0026_add_shiftertype_and_section'),
    ]

    operations = [
        # Rename entrydate → dateworked on BusinessEntry (table is empty, safe)
        migrations.RemoveField(
            model_name='businessentry',
            name='entrydate',
        ),
        migrations.AddField(
            model_name='businessentry',
            name='dateworked',
            field=models.DateField(db_column='DateWorked', default='2026-01-01'),
            preserve_default=False,
        ),
        # Add province to StatHoliday
        migrations.AddField(
            model_name='statholiday',
            name='province',
            field=models.CharField(
                db_column='Province',
                max_length=2,
                choices=[('ON', 'Ontario'), ('QC', 'Quebec')],
                blank=True,
                null=True,
            ),
        ),
    ]
