from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('timesheets', '0023_contract_series_m2m'),
        ('users', '0005_add_crewcoverage'),
    ]

    operations = [
        migrations.AddField(
            model_name='operationsheader',
            name='coverageid',
            field=models.ForeignKey(blank=True, db_column='CoverageID', null=True, on_delete=django.db.models.deletion.SET_NULL, to='users.crewcoverage'),
        ),
    ]
