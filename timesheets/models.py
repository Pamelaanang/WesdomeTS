# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.

from django.db import models


class Auditlog(models.Model):
    logid = models.AutoField(db_column='LogID', primary_key=True)  # Field name made lowercase.
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    action = models.CharField(db_column='Action', max_length=50)  # Field name made lowercase.
    tablename = models.CharField(db_column='TableName', max_length=50)  # Field name made lowercase.
    recordid = models.IntegerField(db_column='RecordID')  # Field name made lowercase.
    oldvalue = models.JSONField(db_column='OldValue', blank=True, null=True)  # Field name made lowercase.
    newvalue = models.JSONField(db_column='NewValue', blank=True, null=True)  # Field name made lowercase.
    timestamp = models.DateTimeField(db_column='Timestamp')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'AuditLog'


class Crews(models.Model):
    crewid = models.AutoField(db_column='CrewID', primary_key=True)  # Field name made lowercase.
    crewname = models.CharField(db_column='CrewName', max_length=10)  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'Crews'


class Timesheetentry(models.Model):
    entryid = models.AutoField(db_column='EntryID', primary_key=True)  # Field name made lowercase.
    headerid = models.ForeignKey('Timesheetheader', models.DO_NOTHING, db_column='HeaderID')  # Field name made lowercase.
    workorderid = models.ForeignKey('Workordercache', models.DO_NOTHING, db_column='WorkOrderID', blank=True, null=True)  # Field name made lowercase.
    workcategoryid = models.ForeignKey('Workcategory', models.DO_NOTHING, db_column='WorkCategoryID')  # Field name made lowercase.
    shifttype = models.CharField(db_column='ShiftType', max_length=5)  # Field name made lowercase.
    hoursworked = models.DecimalField(db_column='HoursWorked', max_digits=5, decimal_places=2)  # Field name made lowercase.
    entrydescription = models.TextField(db_column='EntryDescription', blank=True, null=True)  # Field name made lowercase.
    startdate = models.DateField(db_column='StartDate')  # Field name made lowercase.
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)  # Field name made lowercase.
    linestatus = models.CharField(db_column='LineStatus', max_length=8)  # Field name made lowercase.
    approvedat = models.DateTimeField(db_column='ApprovedAt', blank=True, null=True)  # Field name made lowercase.
    supervisornote = models.TextField(db_column='SupervisorNote', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'TimesheetEntry'


class Timesheetheader(models.Model):
    headerid = models.AutoField(db_column='HeaderID', primary_key=True)  # Field name made lowercase.
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    crewid = models.ForeignKey(Crews, models.DO_NOTHING, db_column='CrewID', blank=True, null=True)  # Field name made lowercase.
    overallstatus = models.CharField(db_column='OverallStatus', max_length=9)  # Field name made lowercase.
    startedat = models.DateTimeField(db_column='StartedAt')  # Field name made lowercase.
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'TimesheetHeader'


class Workcategory(models.Model):
    categoryid = models.AutoField(db_column='CategoryID', primary_key=True)  # Field name made lowercase.
    categoryname = models.CharField(db_column='CategoryName', max_length=255)  # Field name made lowercase.
    isproductive = models.IntegerField(db_column='IsProductive')  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive')  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'WorkCategory'


class Workordercache(models.Model):
    workorderid = models.CharField(db_column='WorkOrderID', primary_key=True, max_length=100)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.
    functionalgroup = models.CharField(db_column='FunctionalGroup', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sap_startdate = models.DateField(db_column='SAP_StartDate')  # Field name made lowercase.
    sap_completiondate = models.DateField(db_column='SAP_CompletionDate', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = False
        db_table = 'WorkOrderCache'
