from django.contrib import admin
from .models import Position, CrewCoverage, User


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('positionname', 'isactive')
    search_fields = ('positionname',)
    ordering = ('positionname',)


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('employeeid', 'firstname', 'lastname', 'roleid', 'shiftertype', 'crewid', 'isactive', 'hasaccess')
    list_filter = ('isactive', 'hasaccess', 'shiftertype', 'crewid')
    search_fields = ('employeeid', 'firstname', 'lastname', 'email')
    ordering = ('lastname', 'firstname')
    fields = (
        'employeeid', 'firstname', 'lastname', 'email', 'phonenumber',
        'roleid', 'supervisorid', 'shiftertype', 'crewid',
        'isactive', 'hasaccess', 'is_temporary',
    )

    def get_readonly_fields(self, request, obj=None):
        # employeeid is the primary key — editing it on an existing row doesn't rename
        # the record, it silently no-ops (see users/management/commands/rename_employee_ids.py
        # for the correct way to do that). Lock it once the object exists.
        return ('employeeid',) if obj else ()


@admin.register(CrewCoverage)
class CrewCoverageAdmin(admin.ModelAdmin):
    list_display = ('covering_shifter', 'home_shifter', 'startdate', 'enddate', 'assignedby', 'assignedat')
    list_filter = ('covering_shifter', 'home_shifter')
    ordering = ('-startdate',)
