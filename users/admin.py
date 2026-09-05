from django.contrib import admin
from .models import Position, CrewCoverage, User, Department, Roles, Accesslevel


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('departmentname', 'isactive')
    search_fields = ('departmentname',)
    ordering = ('departmentname',)


@admin.register(Roles)
class RolesAdmin(admin.ModelAdmin):
    list_display = ('rolename', 'departmentid', 'accessid', 'vacationhours', 'isuniqueassignment')
    list_filter = ('departmentid', 'accessid')
    search_fields = ('rolename',)
    ordering = ('departmentid__departmentname', 'rolename')


@admin.register(Accesslevel)
class AccesslevelAdmin(admin.ModelAdmin):
    list_display = ('accessid', 'accessrole', 'accessdescription')
    ordering = ('accessid',)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('positionname', 'isactive')
    search_fields = ('positionname',)
    ordering = ('positionname',)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('employeeid', 'firstname', 'lastname', 'roleid', 'shiftertype', 'crewid', 'employmenttype', 'isactive', 'hasaccess')
    list_filter = ('isactive', 'hasaccess', 'shiftertype', 'crewid', 'employmenttype')
    search_fields = ('employeeid', 'firstname', 'lastname', 'email')
    ordering = ('lastname', 'firstname')
    fields = (
        'eid', 'employeeid', 'firstname', 'lastname', 'email', 'phonenumber',
        'roleid', 'supervisorid', 'shiftertype', 'crewid',
        'employmenttype', 'contractid', 'accountid',
        'isactive', 'hasaccess', 'is_temporary',
    )
    # employeeid is a plain unique field now (eid is the primary key), so editing
    # it here is a normal, safely-validated update — no FK cascading needed.
    readonly_fields = ('eid',)


@admin.register(CrewCoverage)
class CrewCoverageAdmin(admin.ModelAdmin):
    list_display = ('covering_shifter', 'home_shifter', 'startdate', 'enddate', 'assignedby', 'assignedat')
    list_filter = ('covering_shifter', 'home_shifter')
    ordering = ('-startdate',)
