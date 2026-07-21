from django.contrib import admin
from .models import ContractSeries, Contract, Account, ContractAccount, EmployeeBonus


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
