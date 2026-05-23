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
        managed = True
        db_table = 'AuditLog'


class Crews(models.Model):
    crewid = models.AutoField(db_column='CrewID', primary_key=True)  # Field name made lowercase.
    crewname = models.CharField(db_column='CrewName', max_length=10)  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'Crews'


class MainEntry(models.Model):
    mainentryid = models.AutoField(db_column='MainEntryID', primary_key=True)  # Field name made lowercase.
    mainheaderid = models.ForeignKey('MainHeader', models.DO_NOTHING, db_column='MainHeaderID')  # Field name made lowercase.
    workorderid = models.ForeignKey('Workordercache', models.DO_NOTHING, db_column='WorkOrderID', blank=True, null=True)  # Field name made lowercase.
    workcategoryid = models.ForeignKey('Workcategory', models.DO_NOTHING, db_column='WorkCategoryID')  # Field name made lowercase.
    shifttype = models.CharField(db_column='ShiftType', max_length=5,  choices=[('Day', 'Day'), ('Night', 'Night')])  # Field name made lowercase.
    hoursworked = models.DecimalField(db_column='HoursWorked', max_digits=5, decimal_places=2)  # Field name made lowercase.
    entrydescription = models.TextField(db_column='EntryDescription', blank=True, null=True)  # Field name made lowercase.
    startdate = models.DateField(db_column='StartDate')  # Field name made lowercase.
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)  # Field name made lowercase.
    linestatus = models.CharField(db_column='LineStatus', max_length=15, default='Draft')  # Field name made lowercase.
    approvedat = models.DateTimeField(db_column='ApprovedAt', blank=True, null=True)  # Field name made lowercase.
    approvedby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ApprovedBy', blank=True, null=True, related_name='approved_%(class)s')
    supervisornote = models.TextField(db_column='SupervisorNote', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'MainEntry'


class MainHeader(models.Model):
    mainheaderid = models.AutoField(db_column='MainHeaderID', primary_key=True)  # Field name made lowercase.
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    crewid = models.ForeignKey(Crews, models.DO_NOTHING, db_column='CrewID', blank=True, null=True)  # Field name made lowercase.
    overallstatus = models.CharField(db_column='OverallStatus', max_length=25, default='Draft')  # Field name made lowercase.
    startedat = models.DateTimeField(db_column='StartedAt', auto_now_add=True)  # Field name made lowercase.
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)  # Field name made lowercase.
    
    class Meta:
        managed = True
        db_table = 'MainHeader'


class Workcategory(models.Model):
    categoryid = models.AutoField(db_column='CategoryID', primary_key=True)  # Field name made lowercase.
    categoryname = models.CharField(db_column='CategoryName', max_length=255)  # Field name made lowercase.
    isproductive = models.IntegerField(db_column='IsProductive')  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'WorkCategory'


class Workordercache(models.Model):
    workorderid = models.CharField(db_column='WorkOrderID', primary_key=True, max_length=100)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.
    functionalgroup = models.CharField(db_column='FunctionalGroup', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sap_startdate = models.DateField(db_column='SAP_StartDate')  # Field name made lowercase.
    sap_completiondate = models.DateField(db_column='SAP_CompletionDate', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'WorkOrderCache'


class Contract(models.Model):
    contractid= models.AutoField(db_column='ContractID', primary_key=True)
    contractcode = models.CharField(db_column='ContractCode', max_length=20)
    contracttitle = models.CharField(db_column='ContractTitle', max_length=255)
    contractdescription = models.TextField(db_column='ContractDescription', blank=True, null=True)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Contract'


class Account(models.Model):
    accountid = models.AutoField(db_column='AccountID', primary_key=True)
    accountcode = models.CharField(db_column='AccountCode', max_length=20)
    accounttitle = models.CharField(db_column='AccountTitle', max_length=255)
    accountdescription = models.TextField(db_column='AccountDescription', blank=True, null=True)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Account'


class OperationsHeader(models.Model):
    opsheaderid = models.AutoField(db_column='OpsHeaderID', primary_key=True)
    shifterid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ShifterID')
    shiftdate = models.DateField(db_column='ShiftDate')
    shifttype = models.CharField(db_column='ShiftType', max_length=5, choices=[('Day', 'Day'), ('Night', 'Night')])
    overallstatus = models.CharField(db_column='OverallStatus', max_length=25, default='Draft')
    startedat = models.DateTimeField(db_column='StartedAt', auto_now_add=True)
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'OperationsHeader'


class OperationsEntry(models.Model):
    opsentryid = models.AutoField(db_column='OpsEntryID', primary_key=True)
    opsheaderid = models.ForeignKey(OperationsHeader, models.DO_NOTHING, db_column='OpsHeaderID')
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')
    contractid = models.ForeignKey(Contract, models.DO_NOTHING, db_column='ContractID')
    accountid = models.ForeignKey(Account, models.DO_NOTHING, db_column='AccountID')
    hoursworked = models.DecimalField(db_column='HoursWorked', max_digits=5, decimal_places=2)
    entrydescription = models.TextField(db_column='EntryDescription', blank=True, null=True)
    linestatus = models.CharField(db_column='LineStatus', max_length=15, default='Draft')
    approvedat = models.DateTimeField(db_column='ApprovedAt', blank=True, null=True)
    approvedby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ApprovedBy', blank=True, null=True, related_name='approved_%(class)s')
    captainnote = models.TextField(db_column='CaptainNote', blank=True, null=True)
    superintendentnote = models.TextField(db_column='SuperintendentNote', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'OperationsEntry'