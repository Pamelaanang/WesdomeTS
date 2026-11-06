# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.

from datetime import datetime

from django.db import models
from django.db.models import Min
from django.utils import timezone


def submission_deadline(year, month):
    """5th of the month after (year, month), end of day, tz-aware — the
    normal (soft) cutoff for submitting that month's personal timesheet.
    Submitting after this is still allowed; it's just flagged late."""
    if month == 12:
        deadline_year, deadline_month = year + 1, 1
    else:
        deadline_year, deadline_month = year, month + 1
    naive = datetime(deadline_year, deadline_month, 5, 23, 59, 59)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


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

    def clean(self):
        # A single crew (A, B, C, ...) is told apart from a joint crew group
        # (AB, CD, ...) purely by name length (see basket_for below) — a name
        # longer than one character that isn't an existing Crew Group's name
        # would silently never resolve a basket. Only fires where something
        # calls full_clean() (an admin form, if this model is ever registered
        # there) — plain .save()/.create() calls, including migrations and
        # tests, are unaffected.
        from django.core.exceptions import ValidationError
        if len(self.crewname) != 1 and not CrewGroup.objects.filter(groupname=self.crewname).exists():
            raise ValidationError({
                'crewname': 'A single crew needs a one-character name (like A, B, C). '
                             'A longer name is read as a joint crew group (like AB), and none exists with this name.',
            })


class CrewGroup(models.Model):
    """A joint unit made of single crews, such as AB or CD. It runs its own
    disciplines (Longhole, Logistics) and has its own shifter in each basket."""
    groupid = models.AutoField(db_column='GroupID', primary_key=True)
    groupname = models.CharField(db_column='GroupName', max_length=10, unique=True)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'CrewGroup'

    def __str__(self):
        return self.groupname


class CrewGroupMember(models.Model):
    memberid = models.AutoField(db_column='MemberID', primary_key=True)
    group = models.ForeignKey(CrewGroup, models.PROTECT, db_column='GroupID', related_name='members')
    crew = models.ForeignKey(Crews, models.PROTECT, db_column='CrewID', related_name='group_memberships')

    class Meta:
        managed = True
        db_table = 'CrewGroupMember'
        unique_together = ('group', 'crew')


class UnitDiscipline(models.Model):
    """Which disciplines a unit runs. A unit is a single crew or a crew group,
    never both. Each row is a basket. Nothing is inherited: a unit runs only
    the disciplines linked to it here."""
    unitdisciplineid = models.AutoField(db_column='UnitDisciplineID', primary_key=True)
    crew = models.ForeignKey(Crews, models.PROTECT, db_column='CrewID', blank=True, null=True, related_name='unit_disciplines')
    group = models.ForeignKey(CrewGroup, models.PROTECT, db_column='GroupID', blank=True, null=True, related_name='unit_disciplines')
    discipline = models.ForeignKey('Discipline', models.PROTECT, db_column='DisciplineID', related_name='unit_links')

    class Meta:
        managed = True
        db_table = 'UnitDiscipline'
        unique_together = (('crew', 'discipline'), ('group', 'discipline'))

    def clean(self):
        # "A unit is a single crew or a crew group, never both" (see the
        # docstring above) — nothing enforced that until now. Only fires
        # through form validation (e.g. the admin), same as Crews.clean().
        from django.core.exceptions import ValidationError
        if bool(self.crew_id) == bool(self.group_id):
            raise ValidationError('Set exactly one of Crew or Group — a basket belongs to a single crew or a crew group, never both and never neither.')

    @property
    def unit_name(self):
        return self.crew.crewname if self.crew_id else self.group.groupname

    @property
    def crew_row(self):
        # The Crews row this basket is filed under: the crew itself, or the joint row for a group.
        if self.crew_id:
            return self.crew
        return Crews.objects.filter(crewname=self.group.groupname).first()


class Discipline(models.Model):
    """A kind of work a basket does (Development, Production, Longhole, ...).
    Sort order sets the row order on the grid. Linked from every record that
    stores a discipline; PROTECT stops a discipline being deleted while in use."""
    disciplineid = models.AutoField(db_column='DisciplineID', primary_key=True)
    name = models.CharField(db_column='Name', max_length=20, unique=True)
    sortorder = models.IntegerField(db_column='SortOrder', default=0)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Discipline'
        ordering = ['sortorder', 'name']

    def __str__(self):
        return self.name


def sync_discipline(sender, instance, **kwargs):
    # Keeps the discipline link in step with the discipline text the app still
    # writes (shiftertype, or section on the operations header). Removed in the
    # cleanup step, once everything reads the link directly.
    name = getattr(instance, 'shiftertype', None) or getattr(instance, 'section', None)
    instance.discipline = Discipline.objects.filter(name=name).first() if name else None


def basket_for(crew, discipline_name):
    """The basket (UnitDiscipline row) a crew and discipline text point at, or None.
    A single crew is its own unit; a joint crew row (AB, CD) maps to its group."""
    if crew is None or not discipline_name:
        return None
    discipline = Discipline.objects.filter(name=discipline_name).first()
    if discipline is None:
        return None
    if len(crew.crewname) == 1:
        return UnitDiscipline.objects.filter(crew=crew, discipline=discipline).first()
    group = CrewGroup.objects.filter(groupname=crew.crewname).first()
    return UnitDiscipline.objects.filter(group=group, discipline=discipline).first() if group else None


def sync_basket(sender, instance, **kwargs):
    # Keeps the assignment's basket in step with the crew and discipline text the
    # app still writes. Removed in the cleanup step, once everything reads the basket.
    instance.basket = basket_for(instance.crewid, instance.shiftertype)


class BasketShifter(models.Model):
    """Who runs a basket and whether it's their home. One active row per basket
    (its shifter) and one active home per shifter. A second-basket lead is an
    active row with is_home off. Ended rows keep their dates as history."""
    basketshifterid = models.AutoField(db_column='BasketShifterID', primary_key=True)
    basket = models.ForeignKey('UnitDiscipline', models.PROTECT, db_column='BasketID', related_name='shifter_rows')
    shifter = models.ForeignKey('users.User', models.PROTECT, db_column='ShifterID', related_name='basket_rows')
    is_home = models.BooleanField(db_column='IsHome', default=False)
    startdate = models.DateField(db_column='StartDate')
    enddate = models.DateField(db_column='EndDate', blank=True, null=True)
    # Guards, set only while the row is active: one shifter per basket, one home per shifter.
    basket_key = models.CharField(db_column='BasketKey', max_length=20, unique=True, null=True, blank=True, editable=False)
    home_key = models.CharField(db_column='HomeKey', max_length=20, unique=True, null=True, blank=True, editable=False)

    def save(self, *args, **kwargs):
        active = self.enddate is None
        self.basket_key = str(self.basket_id) if active else None
        self.home_key = str(self.shifter_id) if active and self.is_home else None
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            extra = [f for f in ('basket_key', 'home_key') if f not in update_fields]
            kwargs['update_fields'] = list(update_fields) + extra
        super().save(*args, **kwargs)

    class Meta:
        managed = True
        db_table = 'BasketShifter'


def sync_user_home(sender, instance, **kwargs):
    """Keeps a shifter's home row in step with their crew and discipline fields.
    Removed in the cleanup step, once the basket table is the only source."""
    today = timezone.now().date()
    # A pending hire holds their basket while IT sets up access, as an active one does.
    holds = instance.isactive or instance.onboarding_status == 'pending'
    basket = basket_for(instance.crewid, instance.shiftertype) if holds else None
    current = BasketShifter.objects.filter(shifter=instance, is_home=True, enddate__isnull=True)
    if basket is not None and current.filter(basket=basket).exists():
        return
    for row in current:
        row.enddate = today
        row.save()
    if basket is not None:
        BasketShifter.objects.create(basket=basket, shifter=instance, is_home=True, startdate=today)


def sync_basket_lead(sender, instance, **kwargs):
    """Keeps a second-basket lead's row in step with the BasketLead record."""
    today = timezone.now().date()
    basket = basket_for(instance.crewid, instance.shiftertype)
    if basket is None:
        return
    current = BasketShifter.objects.filter(
        shifter=instance.shifter, basket=basket, is_home=False, enddate__isnull=True,
    )
    if instance.enddate is not None:
        for row in current:
            row.enddate = today
            row.save()
    elif not current.exists():
        BasketShifter.objects.create(basket=basket, shifter=instance.shifter, is_home=False, startdate=instance.startdate)


class LeaveType(models.Model):
    leavetypeid = models.AutoField(db_column='LeaveTypeID', primary_key=True)  # Field name made lowercase.
    leavetypename = models.CharField(db_column='LeaveTypeName', max_length=255)  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.
    ispayable = models.BooleanField(db_column='IsPayable', default=True)

    class Meta:
        managed = True
        db_table = 'LeaveType'


class LeaveAllocation(models.Model):
    allocationid = models.AutoField(db_column='AllocationID', primary_key=True)  # Field name made lowercase.
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    leavetypeid = models.ForeignKey(LeaveType, models.DO_NOTHING, db_column='LeaveTypeID')  # Field name made lowercase.
    year = models.IntegerField(db_column='Year')  # Field name made lowercase.
    allocatedhours = models.DecimalField(db_column='AllocatedHours', max_digits=5, decimal_places=2)  # Field name made lowercase.
    isprorated = models.IntegerField(db_column='IsProrated', default=0)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'LeaveAllocation'


class StatHoliday(models.Model):
    PROVINCE_CHOICES = [('ON', 'Ontario'), ('QC', 'Quebec')]
    statid = models.AutoField(db_column='StatID', primary_key=True)
    statname = models.CharField(db_column='StatName', max_length=255)
    statdate = models.DateField(db_column='StatDate')
    province = models.CharField(db_column='Province', max_length=2, choices=PROVINCE_CHOICES, blank=True, null=True)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'StatHoliday'


class VacationRatePolicy(models.Model):
    """Effective-dated monthly vacation accrual rate. A rate change is a new
    row with a later effective_year, not a code change — lookup takes the
    latest row at or before the target year. The bucket follows employment
    type for operations (Staff or Contract), not discipline."""
    BUCKET_CHOICES = [
        ('ops_staff', 'Operations - Staff'),
        ('ops_contract', 'Operations - Contract'),
        ('non_operations', 'Non-Operations (Business/Maintenance)'),
    ]
    policyid = models.AutoField(db_column='PolicyID', primary_key=True)
    bucket = models.CharField(db_column='Bucket', max_length=20, choices=BUCKET_CHOICES)
    effective_year = models.IntegerField(db_column='EffectiveYear')
    monthly_rate_hours = models.DecimalField(db_column='MonthlyRateHours', max_digits=4, decimal_places=2)

    class Meta:
        managed = True
        db_table = 'VacationRatePolicy'
        unique_together = ('bucket', 'effective_year')
        ordering = ['bucket', '-effective_year']


class LieuDayLedger(models.Model):
    """One row per stat holiday an eligible (salaried) employee banks a lieu
    day for. Earned when the stat date passes with zero hours logged; Used
    when applied against a Lieu Day entry on approval."""
    STATUS_CHOICES = [('Banked', 'Banked'), ('Used', 'Used')]
    ledgerid = models.AutoField(db_column='LedgerID', primary_key=True)
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')
    statholidayid = models.ForeignKey(StatHoliday, models.DO_NOTHING, db_column='StatHolidayID')
    status = models.CharField(db_column='Status', max_length=10, choices=STATUS_CHOICES, default='Banked')
    earnedat = models.DateTimeField(db_column='EarnedAt', auto_now_add=True)
    usedat = models.DateTimeField(db_column='UsedAt', blank=True, null=True)
    used_entry_type = models.CharField(db_column='UsedEntryType', max_length=20, blank=True, null=True)
    used_entry_id = models.IntegerField(db_column='UsedEntryID', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'LieuDayLedger'
        unique_together = ('employeeid', 'statholidayid')


class MainHeader(models.Model):
    mainheaderid = models.AutoField(db_column='MainHeaderID', primary_key=True)  # Field name made lowercase.
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    crewid = models.ForeignKey(Crews, models.DO_NOTHING, db_column='CrewID', blank=True, null=True)  # Field name made lowercase.
    overallstatus = models.CharField(db_column='OverallStatus', max_length=25, default='Draft')  # Field name made lowercase.
    startedat = models.DateTimeField(db_column='StartedAt', auto_now_add=True)  # Field name made lowercase.
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)  # Field name made lowercase.
    completedat = models.DateTimeField(db_column='CompletedAt', blank=True, null=True)
    paidat = models.DateTimeField(db_column='PaidAt', blank=True, null=True)
    paidby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='PaidBy', blank=True, null=True, related_name='paid_%(class)s')

    class Meta:
        managed = True
        db_table = 'MainHeader'

    @property
    def is_late(self):
        """Submitted after the normal deadline for the earliest-dated entry
        it contains. MainHeader has no period field of its own — the oldest
        entry's month stands in for 'which month was this submission for'."""
        if not self.submittedat:
            return False
        earliest = self.mainentry_set.aggregate(Min('startdate'))['startdate__min']
        if not earliest:
            return False
        return self.submittedat > submission_deadline(earliest.year, earliest.month)


class MainEntry(models.Model):
    mainentryid = models.AutoField(db_column='MainEntryID', primary_key=True)  # Field name made lowercase.
    mainheaderid = models.ForeignKey('MainHeader', models.CASCADE, db_column='MainHeaderID')  # Field name made lowercase.
    workorderid = models.ForeignKey('Workordercache', models.DO_NOTHING, db_column='WorkOrderID', blank=True, null=True)  # Field name made lowercase.
    sapworkid = models.CharField(db_column='SAPWorkID', max_length=100, blank=True, null=True)  # manual entry for now
    workcategoryid = models.ForeignKey('Workcategory', models.DO_NOTHING, db_column='WorkCategoryID',  blank=True, null=True)  # Field name made lowercase.
    leavetypeid = models.ForeignKey('LeaveType', models.DO_NOTHING, db_column='LeaveTypeID', blank=True, null=True)  # Field name made lowercase.
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


class Workcategory(models.Model):
    categoryid = models.AutoField(db_column='CategoryID', primary_key=True)  # Field name made lowercase.
    categoryname = models.CharField(db_column='CategoryName', max_length=255)  # Field name made lowercase.
    isproductive = models.IntegerField(db_column='IsProductive')  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.
    ispayable = models.BooleanField(db_column='IsPayable', default=True)
    isovertime = models.BooleanField(db_column='IsOvertime', default=False)

    class Meta:
        managed = True
        db_table = 'WorkCategory'


class Businesscategory(models.Model):
    businesscategoryid = models.AutoField(db_column='CategoryID', primary_key=True)  # Field name made lowercase.
    categoryname = models.CharField(db_column='CategoryName', max_length=255)  # Field name made lowercase.
    isproductive = models.IntegerField(db_column='IsProductive')  # Field name made lowercase.
    isactive = models.IntegerField(db_column='IsActive', default=1)  # Field name made lowercase.
    ispayable = models.BooleanField(db_column='IsPayable', default=True)
    isovertime = models.BooleanField(db_column='IsOvertime', default=False)

    class Meta:
        managed = True
        db_table = 'BusinessCategory'


class Opscategory(models.Model):
    opscategoryid = models.AutoField(db_column='CategoryID', primary_key=True)
    categoryname = models.CharField(db_column='CategoryName', max_length=255)
    isproductive = models.IntegerField(db_column='IsProductive')
    isactive = models.IntegerField(db_column='IsActive', default=1)
    ispayable = models.BooleanField(db_column='IsPayable', default=True)
    isovertime = models.BooleanField(db_column='IsOvertime', default=False)

    class Meta:
        managed = True
        db_table = 'OpsCategory'
   

MONTH_CHOICES = [(1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'), (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'), (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')]

class BusinessHeader(models.Model):
    businessheaderid = models.AutoField(db_column='BusinessHeaderID', primary_key=True)
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')  # Field name made lowercase.
    crewid = models.ForeignKey(Crews, models.DO_NOTHING, db_column='CrewID', blank=True, null=True)  # Field name made lowercase.
    periodmonth = models.IntegerField(db_column='PeriodMonth', choices=MONTH_CHOICES)
    periodyear = models.IntegerField(db_column='PeriodYear')  # Field name made lowercase.
    overallstatus = models.CharField(db_column='OverallStatus', max_length=25, default='Draft')  # Field name made lowercase.
    startedat = models.DateTimeField(db_column='StartedAt', auto_now_add=True)  # Field name made lowercase.
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)  # Field name made lowercase.
    completedat = models.DateTimeField(db_column='CompletedAt', blank=True, null=True)
    paidat = models.DateTimeField(db_column='PaidAt', blank=True, null=True)
    paidby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='PaidBy', blank=True, null=True, related_name='paid_%(class)s')
    bh_approvedby_capt = models.ForeignKey('users.User', models.DO_NOTHING, db_column='BH_ApprovedBy_Capt', blank=True, null=True, related_name='captain_headerapproved_%(class)s')

    class Meta:
        managed = True
        db_table = 'BusinessHeader'

    @property
    def is_late(self):
        """Submitted after the normal deadline (the 5th of the following month)."""
        if not self.submittedat:
            return False
        return self.submittedat > submission_deadline(self.periodyear, self.periodmonth)


class BusinessEntry(models.Model):
    businessentryid = models.AutoField(db_column='BusinessEntryID', primary_key=True)  # Field name made lowercase.
    businessheaderid = models.ForeignKey('BusinessHeader', models.CASCADE, db_column='BusinessHeaderID')  # Field name made lowercase.
    businesscategoryid = models.ForeignKey('BusinessCategory', models.DO_NOTHING, db_column='BusinessCategoryID', blank=True, null=True)  # Field name made lowercase.
    dateworked = models.DateField(db_column='DateWorked')  # Field name made lowercase.
    leavetypeid = models.ForeignKey('LeaveType', models.DO_NOTHING, db_column='LeaveTypeID', blank=True, null=True)  # Field name made lowercase.
    shifttype = models.CharField(db_column='ShiftType', max_length=5,  choices=[('Day', 'Day'), ('Night', 'Night')], blank=True, null=True)  # Field name made lowercase.
    hoursworked = models.DecimalField(db_column='HoursWorked', max_digits=5, decimal_places=2)  # Field name made lowercase.
    entrydescription = models.TextField(db_column='EntryDescription', blank=True, null=True)  # Field name made lowercase.
    linestatus = models.CharField(db_column='LineStatus', max_length=15, default='Draft')  # Field name made lowercase.
    approvedat = models.DateTimeField(db_column='ApprovedAt', blank=True, null=True)  # Field name made lowercase.
    approvedby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ApprovedBy', blank=True, null=True, related_name='approved_%(class)s')
    supervisornote = models.TextField(db_column='SupervisorNote', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'BusinessEntry'


class Workordercache(models.Model):
    workorderid = models.AutoField(db_column='WorkOrderID', primary_key=True)  # Field name made lowercase.
    description = models.CharField(db_column='Description', max_length=255, blank=True, null=True)  # Field name made lowercase.
    functionalgroup = models.CharField(db_column='FunctionalGroup', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sap_workorder = models.CharField(db_column='SAP_WorkOrder', max_length=255, blank=True, null=True)  # Field name made lowercase.
    sap_startdate = models.DateField(db_column='SAP_StartDate')  # Field name made lowercase.
    sap_completiondate = models.DateField(db_column='SAP_CompletionDate', blank=True, null=True)  # Field name made lowercase.

    class Meta:
        managed = True
        db_table = 'WorkOrderCache'


class ContractSeries(models.Model):
    seriesid = models.AutoField(db_column='SeriesID', primary_key=True)
    seriesname = models.CharField(db_column='SeriesName', max_length=100)
    sortorder = models.IntegerField(db_column='SortOrder', default=0)

    class Meta:
        managed = True
        db_table = 'ContractSeries'
        ordering = ['sortorder', 'seriesname']

    def __str__(self):
        return self.seriesname


class MinerLevel(models.Model):
    """Real rows for the same Lead/1/2/3/4 scale as users.User.minerlevel —
    needed as an actual table (not just a CharField) so Contract can carry a
    genuine many-to-many to it: confirmed one contract can span several
    levels and one level can have several valid contracts, so a single
    nullable field on either side can't represent the real relationship."""
    levelid = models.AutoField(db_column='LevelID', primary_key=True)
    levelcode = models.CharField(db_column='LevelCode', max_length=10, unique=True)
    sortorder = models.IntegerField(db_column='SortOrder', default=0)

    class Meta:
        managed = True
        db_table = 'MinerLevel'
        ordering = ['sortorder', 'levelcode']

    def __str__(self):
        return self.levelcode


class Contract(models.Model):
    contractid= models.AutoField(db_column='ContractID', primary_key=True)
    contractcode = models.CharField(db_column='ContractCode', max_length=20)
    contracttitle = models.CharField(db_column='ContractTitle', max_length=255)
    contractdescription = models.TextField(db_column='ContractDescription', blank=True, null=True)
    series = models.ManyToManyField(ContractSeries, db_table='ContractSeriesMap', blank=True, related_name='contracts')
    levels = models.ManyToManyField(MinerLevel, db_table='ContractLevelMap', blank=True, related_name='contracts')
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Contract'


def contracts_by_miner_level():
    # Contract choices keyed by MinerLevel id. A contract with no Level is
    # unclassified and stays hidden until it is given one.
    by_level = {}
    for level in MinerLevel.objects.all():
        by_level[str(level.levelid)] = [
            {'id': c.contractid, 'label': f'{c.contractcode} — {c.contracttitle}'}
            for c in Contract.objects.filter(isactive=1, levels=level).order_by('contractcode')
        ]
    return by_level


class Account(models.Model):
    accountid = models.AutoField(db_column='AccountID', primary_key=True)
    accountcode = models.CharField(db_column='AccountCode', max_length=20)
    accounttitle = models.CharField(db_column='AccountTitle', max_length=255)
    accountdescription = models.TextField(db_column='AccountDescription', blank=True, null=True)
    isactive = models.IntegerField(db_column='IsActive', default=1)

    class Meta:
        managed = True
        db_table = 'Account'


class ContractAccount(models.Model):
    contractaccountid = models.AutoField(db_column='ContractAccountID', primary_key=True)
    contractid = models.ForeignKey(Contract, models.CASCADE, db_column='ContractID')
    accountid = models.ForeignKey(Account, models.CASCADE, db_column='AccountID')

    class Meta:
        managed = True
        db_table = 'ContractAccount'
        unique_together = (('contractid', 'accountid'),)


class OperationsHeader(models.Model):
    opsheaderid = models.AutoField(db_column='OpsHeaderID', primary_key=True)
    shifterid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ShifterID')
    shiftdate = models.DateField(db_column='ShiftDate')
    shifttype = models.CharField(db_column='ShiftType', max_length=5, choices=[('Day', 'Day'), ('Night', 'Night')])
    crewid = models.ForeignKey(Crews, models.DO_NOTHING, db_column='CrewID')
    overallstatus = models.CharField(db_column='OverallStatus', max_length=25, default='Draft')
    startedat = models.DateTimeField(db_column='StartedAt', auto_now_add=True)
    submittedat = models.DateTimeField(db_column='SubmittedAt', blank=True, null=True)
    ohapprovedby_capt = models.ForeignKey('users.User', models.DO_NOTHING, db_column='OpsHApprovedBy_Capt', blank=True, null=True, related_name='captain_headerapproved_%(class)s')
    ohapprovedat_capt = models.DateTimeField(db_column='OHApprovedAt_Capt', blank=True, null=True)
    coverageid = models.ForeignKey('users.CrewCoverage', models.SET_NULL, db_column='CoverageID', blank=True, null=True)

    SECTION_CHOICES = [
        ('Production', 'Production'),
        ('Development', 'Development'),
        ('Longhole', 'Longhole'),
        ('Logistics', 'Logistics'),
    ]
    section = models.CharField(db_column='Section', max_length=20, choices=SECTION_CHOICES, blank=True, null=True)
    discipline = models.ForeignKey(Discipline, models.PROTECT, db_column='DisciplineID', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'OperationsHeader'


class OperationsEntry(models.Model):
    opsentryid = models.AutoField(db_column='OpsEntryID', primary_key=True)
    opsheaderid = models.ForeignKey(OperationsHeader, models.DO_NOTHING, db_column='OpsHeaderID')
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')
    contractid = models.ForeignKey(Contract, models.DO_NOTHING, db_column='ContractID')
    accountid = models.ForeignKey(Account, models.DO_NOTHING, db_column='AccountID', blank=True, null=True)
    opscategoryid = models.ForeignKey(Opscategory, models.DO_NOTHING, db_column='OpsCategoryID', blank=True, null=True)
    leavetypeid = models.ForeignKey('LeaveType', models.DO_NOTHING, db_column='LeaveTypeID', blank=True, null=True)
    hoursworked = models.DecimalField(db_column='HoursWorked', max_digits=5, decimal_places=2)
    remarks = models.TextField(db_column='Remarks', blank=True, null=True)
    hauledto = models.CharField(db_column='HauledTo', max_length=255, blank=True, null=True)
    tonnesorehauled = models.DecimalField(db_column='TonnesOreHauled', max_digits=8, decimal_places=2, blank=True, null=True)
    tonneswastehauled = models.DecimalField(db_column='TonnesWasteHauled', max_digits=8, decimal_places=2, blank=True, null=True)
    lowgradehauled = models.DecimalField(db_column='LowGradeHauled', max_digits=8, decimal_places=2, blank=True, null=True)
    tonnesoreskipped = models.DecimalField(db_column='TonnesOreSkipped', max_digits=8, decimal_places=2, blank=True, null=True)
    tonneswasteskipped = models.DecimalField(db_column='TonnesWasteSkipped', max_digits=8, decimal_places=2, blank=True, null=True)
    lowgradeskipped = models.DecimalField(db_column='LowGradeSkipped', max_digits=8, decimal_places=2, blank=True, null=True)
    longholefootage = models.DecimalField(db_column='LongHoleFootage', max_digits=8, decimal_places=2, blank=True, null=True)
    linestatus = models.CharField(db_column='LineStatus', max_length=15, default='Draft')
    paidat = models.DateTimeField(db_column='PaidAt', blank=True, null=True)
    paidby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='PaidBy', blank=True, null=True, related_name='paid_%(class)s')
    approvedat_capt = models.DateTimeField(db_column='ApprovedAt_Capt', blank=True, null=True)
    approvedby_capt = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ApprovedBy_Capt', blank=True, null=True, related_name='captain_approved_%(class)s')
    captainnote = models.TextField(db_column='CaptainNote', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'OperationsEntry'


BONUS_RATE_CODES = [('1x','1x'), ('2x','2x'), ('3x','3x'), ('1','1'), ('2','2'), ('3','3'), 
                    ('4','4'), ('5','5'), ('6','6'), ('7','7'), ('8','8'), ]

class OperationsBonus(models.Model):
    opsbonusid = models.AutoField(db_column='OpsBonusID', primary_key=True)
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID')
    bonusmonth = models.DateField(db_column='BonusMonth')
    bonusratecode = models.CharField(db_column='BonusRateCode', max_length=2, choices=BONUS_RATE_CODES)
    notes = models.TextField(db_column='Notes', blank=True, null=True)
    reviewedby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='ReviewedBy', blank=True, null=True, related_name='reviewed_%(class)s')
    reviewedat = models.DateTimeField(db_column='ReviewedAt', blank=True, null=True)
    appliedbypayroll = models.ForeignKey('users.User', models.DO_NOTHING, db_column='AppliedByPayroll', blank=True, null=True, related_name='applied_%(class)s')
    appliedatpayroll = models.DateTimeField(db_column='AppliedAtPayroll', blank=True, null=True)
    status = models.CharField(
        db_column='Status', max_length=10,
        choices=[('Draft', 'Draft'), ('Submitted', 'Submitted'), ('Applied', 'Applied')],
        default='Draft',
    )

    class Meta:
        managed = True
        db_table = 'OperationsBonus'
        unique_together = (('employeeid', 'bonusmonth'),)


BONUS_TYPE_CHOICES = [('Year-End', 'Year-End'), ('Ad-Hoc', 'Ad-Hoc')]

class EmployeeBonus(models.Model):
    employeebonusid = models.AutoField(db_column='EmployeeBonusID', primary_key=True)
    employeeid = models.ForeignKey('users.User', models.DO_NOTHING, db_column='EmployeeID', related_name='bonuses')
    bonustype = models.CharField(db_column='BonusType', max_length=10, choices=BONUS_TYPE_CHOICES)
    periodstart = models.DateField(db_column='PeriodStart')
    periodend = models.DateField(db_column='PeriodEnd')
    bonusratecode = models.CharField(db_column='BonusRateCode', max_length=2, choices=BONUS_RATE_CODES)
    notes = models.TextField(db_column='Notes', blank=True, null=True)
    assignedby = models.ForeignKey('users.User', models.DO_NOTHING, db_column='AssignedBy', related_name='assigned_bonuses')
    assignedat = models.DateTimeField(db_column='AssignedAt', auto_now_add=True)
    status = models.CharField(
        db_column='Status', max_length=10,
        choices=[('Draft', 'Draft'), ('Submitted', 'Submitted'), ('Applied', 'Applied')],
        default='Draft',
    )
    appliedbypayroll = models.ForeignKey('users.User', models.DO_NOTHING, db_column='AppliedByPayroll', blank=True, null=True, related_name='applied_employee_bonuses')
    appliedatpayroll = models.DateTimeField(db_column='AppliedAtPayroll', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'EmployeeBonus'
        ordering = ['-periodend']