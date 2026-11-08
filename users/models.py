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


# Miner levels that can step up as a (temporary) Spare Shifter. Every picker,
# server check and hint reads this, so the rule lives in one place.
SPARE_SHIFTER_LEVELS = ('Lead', '1', '2', '3')
SPARE_SHIFTER_LEVELS_TEXT = 'Lead, 1, 2 or 3'


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

    #Superintendent-added hires awaiting IT system access. Null for everyone else.
    ONBOARDING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('activated', 'Activated'),
        ('rejected', 'Rejected'),
    ]
    onboarding_status = models.CharField(max_length=10, choices=ONBOARDING_STATUS_CHOICES, blank=True, null=True)
    onboarding_requested_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True, related_name='onboarding_requests')
    onboarding_requested_on = models.DateField(blank=True, null=True)
    onboarding_resolved_by = models.ForeignKey('self', models.SET_NULL, blank=True, null=True, related_name='onboarding_resolutions')
    onboarding_resolved_on = models.DateField(blank=True, null=True)

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
    discipline = models.ForeignKey('timesheets.Discipline', models.PROTECT, db_column='DisciplineID', blank=True, null=True)

    #Home crew (A/B/C/D) for Shifters — fixed while active, independent of CrewAssignment roster membership
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True, related_name='shifters')

    #Full Miner (al=8) seniority scale, independent of Spare Shifter eligibility —
    #only the levels in SPARE_SHIFTER_LEVELS (Lead/1/2/3) are ever offered as Spare
    #Shifter candidates; Level 4 is recorded here but never promoted. Null means unclassified.
    #Foreign key to the MinerLevel table (rows: Staff, Lead, 1, 2, 3, 4). Use
    #minerlevel.levelcode when the text is needed.
    minerlevel = models.ForeignKey('timesheets.MinerLevel', db_column='MinerLevelID', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')

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
        """Every (crew, discipline) basket this Shifter currently runs, read from the
        basket table: their home basket and any second-basket lead, plus any basket
        they hold active seats in (e.g. temporarily covering a second basket).
        Shared by crew_assignment_detail and new_ops_sheet so both agree on what
        "my baskets" means."""
        from timesheets.models import BasketShifter
        baskets = {}
        for row in BasketShifter.objects.filter(shifter=self, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline'):
            baskets[row.basket_id] = row.basket
        for a in self.crew_led.filter(enddate__isnull=True, basket__isnull=False).select_related('basket__crew', 'basket__group', 'basket__discipline'):
            baskets[a.basket_id] = a.basket
        pairs = [(b.crew_row, b.discipline.name) for b in baskets.values() if b.crew_row is not None]
        return sorted(pairs, key=lambda b: (b[0].crewname, b[1]))

    @property
    def home_basket(self):
        # The basket this shifter is home in (active, or pending IT access), or None.
        from timesheets.models import BasketShifter
        row = BasketShifter.objects.filter(shifter=self, is_home=True, enddate__isnull=True).select_related('basket__crew', 'basket__group', 'basket__discipline').first()
        return row.basket if row else None

    @property
    def mine_captains(self):
        """The Mine Captains shown as a Shifter's supervisors. Any captain can
        approve any Shifter (personal sheets by claim, crew sheets first come
        first served), so this is every captain who can still approve: active,
        and not past a recorded last day. Display only; approvals never read it."""
        from django.db.models import Q
        from django.utils import timezone
        today = timezone.localdate()
        return User.objects.filter(
            Q(terminationdate__isnull=True) | Q(terminationdate__gte=today),
            roleid__accessid__accessid=4, isactive=True,
        ).order_by('lastname', 'firstname')

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
    discipline = models.ForeignKey('timesheets.Discipline', models.PROTECT, db_column='DisciplineID', blank=True, null=True)
    # Row order within the position's discipline on the grid (lower first), shared by every crew.
    sortorder = models.IntegerField(db_column='SortOrder', default=0)

    class Meta:
        managed = True
        db_table = 'Position'
        ordering = ['positionname']

    def __str__(self):
        return self.positionname


class CrewCoverage(models.Model):
    coverageid = models.AutoField(db_column='CoverageID', primary_key=True)
    covering_shifter = models.ForeignKey('User', models.DO_NOTHING, db_column='CoveringShifterID', related_name='coverages_covering')
    home_shifter = models.ForeignKey('User', models.DO_NOTHING, db_column='HomeShifterID', related_name='coverages_home', blank=True, null=True)

    #Which basket this covers — recorded explicitly rather than derived from
    #home_shifter's own crewid/shiftertype at end time, since a shifter can
    #run two baskets at once (Transfer already allows it) and that would
    #otherwise leave it ambiguous which one the covering party is standing
    #in for. Nullable only because historical rows predate this field.
    crewid = models.ForeignKey('timesheets.Crews', models.SET_NULL, db_column='CrewID', blank=True, null=True)
    shiftertype = models.CharField(db_column='ShifterType', max_length=20, choices=User.SHIFTER_TYPE_CHOICES, blank=True, null=True)
    discipline = models.ForeignKey('timesheets.Discipline', models.PROTECT, db_column='DisciplineID', blank=True, null=True)
    basket = models.ForeignKey('timesheets.UnitDiscipline', models.PROTECT, db_column='BasketID', blank=True, null=True, related_name='coverages')

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
    def home_label(self):
        if self.home_shifter:
            return f'{self.home_shifter.firstname} {self.home_shifter.lastname}'
        return 'vacant basket'

    @property
    def home_is_live(self):
        return bool(self.home_shifter and self.home_shifter.isactive and self.home_shifter.access_level == 5)

    @property
    def basket_crew(self):
        if self.crewid_id:
            return self.crewid
        return self.home_shifter.crewid if self.home_shifter else None

    @property
    def basket_shiftertype(self):
        if self.shiftertype:
            return self.shiftertype
        return self.home_shifter.shiftertype if self.home_shifter else None

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
    discipline = models.ForeignKey('timesheets.Discipline', models.PROTECT, db_column='DisciplineID', blank=True, null=True)

    #Grid-display-only — lets this one row's cell visually merge into a
    #joint crew's column (e.g. a Production position covering both Crew A
    #and Crew B) without changing which basket it actually belongs to for
    #every other purpose. crewid/shiftertype above stay canonical and keep
    #driving Ops Sheet derivation, Coverage, Transfer, Demote, etc.,
    #completely unchanged — nothing outside crew_grid ever reads this field.
    #Expected values are the real "AB"/"CD" Crews rows only, never a new pairing.

    #The basket (unit + discipline) this seat sits in. Position's discipline must match it.
    basket = models.ForeignKey('timesheets.UnitDiscipline', models.PROTECT, db_column='BasketID', blank=True, null=True, related_name='assignments')

    #Database guard: one active assignment per person. Set to the employee while
    #the assignment is open, empty once it ends, so a second open seat is refused.
    active_employee_key = models.CharField(db_column='ActiveEmployeeKey', max_length=20, unique=True, null=True, blank=True, editable=False)


    # The other crew this seat also covers, as a basket for the same discipline. Empty when
    # the seat covers only its primary basket. The crew rules come from the unit links.
    also_covers_basket = models.ForeignKey('timesheets.UnitDiscipline', models.PROTECT, db_column='AlsoCoversBasketID', blank=True, null=True, related_name='also_covering_seats')

    def save(self, *args, **kwargs):
        self.active_employee_key = None if self.enddate else str(self.employee_id)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'active_employee_key' not in update_fields:
            kwargs['update_fields'] = list(update_fields) + ['active_employee_key']
        super().save(*args, **kwargs)

    class Meta:
        managed = True
        db_table = 'CrewAssignment'

class BasketLead(models.Model):
    """A shifter leading a basket they don't call home — recorded even when the
    basket has no members yet, so an empty second basket still has a leader."""
    basketleadid = models.AutoField(primary_key=True)
    shifter = models.ForeignKey('User', models.DO_NOTHING, related_name='basket_leads')
    crewid = models.ForeignKey('timesheets.Crews', models.DO_NOTHING)
    shiftertype = models.CharField(max_length=20, choices=User.SHIFTER_TYPE_CHOICES)
    discipline = models.ForeignKey('timesheets.Discipline', models.PROTECT, db_column='DisciplineID', blank=True, null=True)
    basket = models.ForeignKey('timesheets.UnitDiscipline', models.PROTECT, db_column='BasketID', blank=True, null=True, related_name='lead_records')
    startdate = models.DateField()
    enddate = models.DateField(blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'BasketLead'
