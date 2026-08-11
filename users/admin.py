from django.contrib import admin
from .models import Position, CrewCoverage


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('positionname', 'isactive')
    search_fields = ('positionname',)
    ordering = ('positionname',)


@admin.register(CrewCoverage)
class CrewCoverageAdmin(admin.ModelAdmin):
    list_display = ('covering_shifter', 'home_shifter', 'startdate', 'enddate', 'assignedby', 'assignedat')
    list_filter = ('covering_shifter', 'home_shifter')
    ordering = ('-startdate',)
