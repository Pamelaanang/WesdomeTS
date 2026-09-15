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
    showsleavebalance = models.BooleanField(db_column='ShowsLeaveBalance', default=False)

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
        extra_fields.setdefault('is_superuser', True)
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        return self.create_user(employeeid, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    #Surrogate primary key — EmployeeID stays a stable, human-editable business
    #identifier (unique, not the PK), so renaming it never has to touch every
    #table that references this employee. Every ForeignKey(User, ...) elsewhere
    #in the codebase targets whatever this model's PK is with no to_field
    #override, so they all automatically follow EID instead of EmployeeID.
    eid = models.AutoField(db_column='EID', primary_key=True)

    #Identity required fields
    employeeid = models.CharField(db_column='EmployeeID', max_length=255, unique=True)  # Field name made lowercase.
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

    #HR dates — nullable since no historical hire dates are on file yet; backfilled manually over time.
    hiredate = models.DateField(db_column='HireDate', blank=True, null=True)
    terminationdate = models.DateField(db_column='TerminationDate', blank=True, null=True)

    SHIFTER_TYPE_CHOICES = [
        ('Production', 'Production'),
        ('Development', 'Development'),
        ('Longhole', 'Longhole'),
        ('Logistics', 'Logistics'),
    ]
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=SHIFTER_TYPE_CHOICES, blank=True, null=True)

    #Home crew (A/B/C/D) for Shifters — fixed while active, independent of CrewAssignment roster membership
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True, related_name='shifters')

    #Full Miner (al=8) seniority scale, independent of Spare Shifter eligibility —
    #only Lead/1/2 are ever offered as Spare Shifter candidates (see crew_coverage
    #view); Levels 3/4 are recorded here but never promoted. Null means unclassified.
    MINER_LEVEL_CHOICES = [
        ('Staff', 'Staff'),
        ('Lead', 'Lead'),
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
    ]
    minerlevel = models.CharField(db_column='MinerLevel', max_length=6, choices=MINER_LEVEL_CHOICES, blank=True, null=True)

    #HR/payroll classification — Staff vs Contract labor. Contract cost is charged to
    #a designated contract/account for reporting, separate from per-entry billing.
    EMPLOYMENT_TYPE_CHOICES = [
        ('Staff', 'Staff'),
        ('Contract', 'Contract'),
    ]
    employmenttype = models.CharField(db_column='EmploymentType', max_length=10, choices=EMPLOYMENT_TYPE_CHOICES, default='Staff')
    contractid = models.ForeignKey('timesheets.Contract', models.SET_NULL, db_column='ContractID', blank=True, null=True, related_name='contract_employees')
    accountid = models.ForeignKey('timesheets.Account', models.SET_NULL, db_column='AccountID', blank=True, null=True, related_name='account_employees')

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

    def get_active_baskets(self):
        """Every distinct (crewid, shiftertype) basket this Shifter currently
        operates — their home basket (crewid/shiftertype on their own record)
        plus any other basket picked up via active CrewAssignment rows (e.g.
        temporarily covering a second basket). Almost always just the one
        home basket. Shared by crew_assignment_detail and new_ops_sheet so
        both agree on what "my baskets" means."""
        baskets = {}
        if self.crewid_id and self.shiftertype:
            baskets[(self.crewid_id, self.shiftertype)] = (self.crewid, self.shiftertype)
        for a in self.crew_led.filter(enddate__isnull=True).select_related('crewid'):
            if a.crewid_id and a.shiftertype:
                baskets[(a.crewid_id, a.shiftertype)] = (a.crewid, a.shiftertype)
        return sorted(baskets.values(), key=lambda b: (b[0].crewname, b[1]))

    @property
    def has_maintenance_reports(self):
        """Whether any direct report is Maintenance Crew (al=9) — i.e. whether
        this supervisor actually has a Maintenance approval queue to see.
        Mirrors approval_inbox's own ownership query exactly, so the nav link
        it gates is never a dead end (e.g. an HR Manager with no crew reports
        never sees it; a real Maintenance Supervisor always does)."""
        return User.objects.filter(supervisorid=self, roleid__accessid__accessid=9).exists()

    @property
    def has_business_reports(self):
        """Whether any direct report is a non-Shifter Business-side filer
        (Supervisor/Mine Captain/Business Employee) — i.e. whether this
        supervisor has a Business approval queue to see. Shifters (al=5)
        route to Mine Captains via the claim model, not their supervisorid,
        so they're excluded here exactly as business_approval_inbox excludes them."""
        return User.objects.filter(supervisorid=self, roleid__accessid__accessid__in=[3, 4, 6]).exists()

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

    #Which basket discipline this position belongs to — same four values as
    #User.shiftertype. Nullable: existing legacy positions start unclassified
    #and get sorted into a discipline gradually by the Superintendent via the
    #Position Catalog page, rather than all at once in a migration.
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=User.SHIFTER_TYPE_CHOICES, blank=True, null=True)

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

    #Which basket this covers — recorded explicitly rather than derived from
    #home_shifter's own crewid/shiftertype at end time, since a shifter can
    #run two baskets at once (Transfer already allows it) and that would
    #otherwise leave it ambiguous which one the covering party is standing
    #in for. Nullable only because historical rows predate this field.
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True)
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=User.SHIFTER_TYPE_CHOICES, blank=True, null=True)

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

    #Nullable so a basket can go leaderless (shifter promoted/demoted/moved
    #on) without ending the crew's own assignments — the roster stays put,
    #the grid just shows that basket as "Unassigned" until someone new is
    #placed there, temporarily or permanently.
    shifter = models.ForeignKey(User, models.DO_NOTHING, db_column='ShifterID', related_name='crew_led', blank=True, null=True)
    employee = models.ForeignKey('User', models.DO_NOTHING, db_column='EmployeeID', related_name='crew_assignments')
    positionid = models.ForeignKey(Position, models.SET_NULL, db_column='PositionID', blank=True, null=True)
    startdate = models.DateField(db_column='StartDate')
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)

    #Basket (crew + discipline) this assignment belongs to — recorded on the row
    #itself rather than inferred from the shifter's own crewid/shiftertype, so a
    #shifter can hold active assignments under more than one basket at once (e.g.
    #temporarily covering a second basket) without ambiguity. Auto-stamped from
    #whichever basket page an assignment is created on — never a field a user
    #picks directly. Nullable only so existing rows can be backfilled.
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True)
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=User.SHIFTER_TYPE_CHOICES, blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'CrewAssignment'