from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

class Accesslevel(models.Model):
    accessid = models.AutoField(db_column='AccessID', primary_key=True)  # Field name made lowercase.
    accessrole = models.CharField(db_column='AccessRole', max_length=255)  # Field name made lowercase.
    accessdescription = models.CharField(db_column='AccessDescription', max_length=500, blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'AccessLevel'


class Department(models.Model):
    departmentid = models.AutoField(db_column='DepartmentID', primary_key=True)  # Field name made lowercase.
    departmentname = models.CharField(db_column='DepartmentName', max_length=255)  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'Department'


class Roles(models.Model):
    roleid = models.AutoField(db_column='RoleID', primary_key=True)  # Field name made lowercase.
    rolename = models.CharField(db_column='RoleName', max_length=100)  # Field name made lowercase.
    vacationhours = models.IntegerField(db_column='VacationHours', blank=True, null=True)  # Field name made lowercase.
    departmentid = models.ForeignKey(Department, models.DO_NOTHING, db_column='DepartmentID')  # Field name made lowercase.
    accessid = models.ForeignKey(Accesslevel, models.DO_NOTHING, db_column='AccessID')  # Field name made lowercase.
    isuniqueassignment = models.IntegerField(db_column='IsUniqueAssignment', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'Roles'


class EmployeeManager(BaseUserManager):
    def get_by_natural_key(self, employeeid):
        return self.get(employeeid=employeeid)
    
    def create_user(self, employeeid, password=None, **extra_fields):
        extra_fields.setdefault('is_temporary', True)
        extra_fields.setdefault('isactive', True)
        user = self.model(employeeid=employeeid, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, employeeid, password=None, **extra_fields):
        extra_fields.setdefault('is_temporary', False)
        extra_fields.setdefault('isactive', True)
        return self.create_user(employeeid, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    #Identity required fields
    employeeid = models.CharField(db_column='EmployeeID', max_length=255, primary_key=True)  # Field name made lowercase.
    #Django uses. 'password' internally. Hence we point 'passpin' to its internal 'password'
    password = models.CharField(db_column='Passpin', max_length=255, blank=True, null=True)  # Field name made lowercase.

    # Required for Twilio/First-time login
    phonenumber = models.CharField(db_column='PhoneNumber', max_length=20)  # Field name made lowercase.

    #Personal Information (Email is optional)
    firstname = models.CharField(db_column='FirstName', max_length=100)  # Field name made lowercase.
    lastname = models.CharField(db_column='LastName', max_length=100)  # Field name made lowercase.
    email = models.EmailField(db_column='Email', unique=True, max_length=255, blank=True, null=True)  # Field name made lowercase.

    #Status Flags
    # 1 yes, temporary and 0 is No permanent (Django Boolean handles this)
    is_temporary = models.BooleanField(db_column='is_temporary', default=True)
    isactive = models.BooleanField(db_column='IsActive')
    hasaccess = models.BooleanField(db_column='HasAccess', default=True)

    #Foreign key to roles table
    roleid = models.ForeignKey('Roles', models.DO_NOTHING, db_column='RoleID')  # Field name made lowercase.

    #Login details
    lastlogin = models.DateTimeField(db_column='LastLogin', blank=True, null=True)  # Field name made lowercase.
    lastresetdate = models.DateTimeField(db_column='LastResetDate', blank=True, null=True)  # Field name made lowercase.

    #Additional Data
    profilepic = models.CharField(db_column='ProfilePic', max_length=255, blank=True, null=True)  # Field name made lowercase.
    supervisorid = models.ForeignKey('self', models.DO_NOTHING, db_column='SupervisorID', blank=True, null=True)  # Field name made lowercase.
    microsoftid = models.CharField(db_column='MicrosoftID', max_length=255, blank=True, null=True)  # Field name made lowercase.

    SHIFTER_TYPE_CHOICES = [
        ('Production', 'Production'),
        ('Development', 'Development'),
        ('Longhole', 'Longhole'),
        ('Logistics', 'Logistics'),
    ]
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=SHIFTER_TYPE_CHOICES, blank=True, null=True)

    #Home crew (A/B/C/D) for Shifters — fixed while active, independent of CrewAssignment roster membership
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True, related_name='shifters')

    objects = EmployeeManager()

    #Tell Django which variable to use for Authentication
    USERNAME_FIELD = 'employeeid'
    REQUIRED_FIELDS = ['phonenumber', 'firstname', 'lastname']

    class Meta:
        managed = True
        db_table = 'Employee'

    @property
    def access_level(self):
        """
        Since Access Level is in a separate table linked via Role,
        we will write a helper to fetch it.
        """
        #We will implement the actual Join logic here once the
        #Role and AccessLevel models are generated.
        if self.roleid and self.roleid.accessid:
            return self.roleid.accessid.accessid
        return None

    @property
    def is_staff(self):
        #System Admin (1) and potentially others get staff/admin access
        return self.access_level == 1

    @property
    def is_active(self):
        #Connects Django's is_active to localized isactive to required for login to avoid a clash and permit login
        return self.isactive


class Position(models.Model):
    positionid = models.AutoField(db_column='PositionID', primary_key=True)
    positionname = models.CharField(db_column='PositionName', max_length=100)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Position'
        ordering = ['positionname']

    def __str__(self):
        return self.positionname


class CrewCoverage(models.Model):
    coverageid = models.AutoField(db_column='CoverageID', primary_key=True)
    covering_shifter = models.ForeignKey('User', models.DO_NOTHING, db_column='CoveringShifterID', related_name='coverages_covering')
    home_shifter = models.ForeignKey('User', models.DO_NOTHING, db_column='HomeShifterID', related_name='coverages_home')
    startdate = models.DateField(db_column='StartDate')
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)
    notes = models.TextField(db_column='Notes', blank=True, null=True)
    assignedby = models.ForeignKey('User', models.DO_NOTHING, db_column='AssignedBy', related_name='coverages_assigned')
    assignedat = models.DateTimeField(db_column='AssignedAt', auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'CrewCoverage'
        ordering = ['-startdate']

    def __str__(self):
        return f"{self.covering_shifter} covering {self.home_shifter}"

    @property
    def is_active(self):
        from django.utils import timezone
        today = timezone.now().date()
        return self.startdate <= today and (self.enddate is None or self.enddate >= today)


class CrewAssignment(models.Model):
    assignmentid = models.AutoField(db_column='AssignmentID', primary_key=True)
    shifter = models.ForeignKey(User, models.DO_NOTHING, db_column='ShifterID', related_name='crew_led')
    employee = models.ForeignKey('User', models.DO_NOTHING, db_column='EmployeeID', related_name='crew_assignments')
    positionid = models.ForeignKey(Position, models.SET_NULL, db_column='PositionID', blank=True, null=True)
    startdate = models.DateField(db_column='StartDate')
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'CrewAssignment'