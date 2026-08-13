from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0024_ops_header_coverage'),
    ]

    operations = [
        migrations.AddField(
            model_name='operationsbonus',
            name='status',
            field=models.CharField(
                db_column='Status',
                max_length=10,
                choices=[('Draft', 'Draft'), ('Submitted', 'Submitted'), ('Applied', 'Applied')],
                default='Draft',
            ),
        ),
    ]
