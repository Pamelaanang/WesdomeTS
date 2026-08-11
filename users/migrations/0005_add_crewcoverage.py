from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_add_position'),
    ]

    operations = [
        migrations.CreateModel(
            name='CrewCoverage',
            fields=[
                ('coverageid', models.AutoField(db_column='CoverageID', primary_key=True, serialize=False)),
                ('startdate', models.DateField(db_column='StartDate')),
                ('enddate', models.DateField(blank=True, db_column='EndDate', null=True)),
                ('notes', models.TextField(blank=True, db_column='Notes', null=True)),
                ('assignedat', models.DateTimeField(auto_now_add=True, db_column='AssignedAt')),
                ('assignedby', models.ForeignKey(db_column='AssignedBy', on_delete=django.db.models.deletion.DO_NOTHING, related_name='coverages_assigned', to='users.user')),
                ('covering_shifter', models.ForeignKey(db_column='CoveringShifterID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='coverages_covering', to='users.user')),
                ('home_shifter', models.ForeignKey(db_column='HomeShifterID', on_delete=django.db.models.deletion.DO_NOTHING, related_name='coverages_home', to='users.user')),
            ],
            options={
                'db_table': 'CrewCoverage',
                'ordering': ['-startdate'],
                'managed': True,
            },
        ),
    ]
