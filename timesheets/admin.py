from django.contrib import admin
from .models import (
    ContractSeries, Contract, Account, ContractAccount, EmployeeBonus,
    LeaveType, LeaveAllocation, VacationRatePolicy, LieuDayLedger,
    Workcategory, Businesscategory, Opscategory,
)


@admin.register(ContractSeries)
class ContractSeriesAdmin(admin.ModelAdmin):
    list_display = ('seriesname', 'sortorder', 'contract_count')
    ordering = ('sortorder', 'seriesname')

    def contract_count(self, obj):
        return obj.contracts.count()
    contract_count.short_description = 'Contracts'


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('contractcode', 'contracttitle', 'isactive')
    list_filter = ('series', 'isactive')
    search_fields = ('contractcode', 'contracttitle')
    filter_horizontal = ('series',)
    ordering = ('contractcode',)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('accountcode', 'accounttitle', 'isactive')
    search_fields = ('accountcode', 'accounttitle')


@admin.register(EmployeeBonus)
class EmployeeBonusAdmin(admin.ModelAdmin):
    list_display = ('employeeid', 'bonustype', 'periodstart', 'periodend', 'bonusratecode', 'assignedby', 'appliedatpayroll')
    list_filter = ('bonustype', 'bonusratecode')
    search_fields = ('employeeid__firstname', 'employeeid__lastname')


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('leavetypename', 'isactive', 'ispayable')
    list_editable = ('isactive', 'ispayable')


@admin.register(Workcategory)
class WorkcategoryAdmin(admin.ModelAdmin):
    list_display = ('categoryname', 'isproductive', 'isactive', 'ispayable')
    list_editable = ('isproductive', 'isactive', 'ispayable')
    search_fields = ('categoryname',)


@admin.register(Businesscategory)
class BusinesscategoryAdmin(admin.ModelAdmin):
    list_display = ('categoryname', 'isproductive', 'isactive', 'ispayable')
    list_editable = ('isproductive', 'isactive', 'ispayable')
    search_fields = ('categoryname',)


@admin.register(Opscategory)
class OpscategoryAdmin(admin.ModelAdmin):
    list_display = ('categoryname', 'isproductive', 'isactive', 'ispayable')
    list_editable = ('isproductive', 'isactive', 'ispayable')
    search_fields = ('categoryname',)


@admin.register(LeaveAllocation)
class LeaveAllocationAdmin(admin.ModelAdmin):
    list_display = ('employeeid', 'leavetypeid', 'year', 'allocatedhours', 'isprorated')
    list_filter = ('leavetypeid', 'year')
    search_fields = ('employeeid__firstname', 'employeeid__lastname')


@admin.register(VacationRatePolicy)
class VacationRatePolicyAdmin(admin.ModelAdmin):
    list_display = ('bucket', 'effective_year', 'monthly_rate_hours')
    list_filter = ('bucket',)
    ordering = ('bucket', '-effective_year')


@admin.register(LieuDayLedger)
class LieuDayLedgerAdmin(admin.ModelAdmin):
    list_display = ('employeeid', 'statholidayid', 'status', 'earnedat', 'usedat')
    list_filter = ('status',)
    search_fields = ('employeeid__firstname', 'employeeid__lastname')
