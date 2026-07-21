from django.urls import path 
from . import views

urlpatterns = [
    path('timesheet/new/', views.new_timesheet, name='new_timesheet'),
    path('timesheet/<int:pk>/', views.add_entry, name='add_entry'),
    path('timesheet/<int:pk>/delete/', views.delete_draft, name='delete_draft'),
    path('timesheet/drafts/', views.my_drafts, name='my_drafts'),
    path('supervisor/inbox/', views.approval_inbox, name='approval_inbox'),
    path('supervisor/review/<int:pk>/', views.review_timesheet, name='review_timesheet'),
    path('payroll/unprocessed/', views.payroll_unprocessed, name='payroll_unprocessed'),
    path('payroll/unprocessed/<int:dept_id>/', views.payroll_unprocessed_dept, name='payroll_unprocessed_dept'),
    path('payroll/unprocessed/<int:dept_id>/timesheet/<int:pk>/', views.payroll_unprocessed_review, name='payroll_unprocessed_review'),
    path('payroll/processed/', views.payroll_processed, name='payroll_processed'),
    path('payroll/processed/employee/<str:employee_id>/', views.payroll_processed_employee, name='payroll_processed_employee'),
    path('operations/new/', views.new_ops_sheet, name='new_ops_sheet'),
    path('operations/my-sheets/', views.my_ops_sheets, name='my_ops_sheets'),
    path('operations/<int:pk>/', views.ops_sheet, name='ops_sheet'),
    path('operations/<int:pk>/delete/', views.delete_ops_draft, name='delete_ops_draft'),
    path('api/accounts/', views.accounts_for_contract, name='accounts_for_contract'),
    path('superintendent/contract-accounts/', views.contract_account_management, name='contract_account_management'),
]