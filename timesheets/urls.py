from django.urls import path 
from . import views

urlpatterns = [
    path('timesheet/new/', views.new_timesheet, name='new_timesheet'),
    path('timesheet/<int:pk>/', views.add_entry, name='add_entry'),
    path('timesheet/drafts/', views.my_drafts, name='my_drafts'),
    path('supervisor/inbox/', views.approval_inbox, name='approval_inbox'),
    path('supervisor/review/<int:pk>/', views.review_timesheet, name='review_timesheet'),
    path('payroll/unprocessed/', views.payroll_unprocessed, name='payroll_unprocessed'),
    path('payroll/unprocessed/<int:dept_id>/', views.payroll_unprocessed_dept, name='payroll_unprocessed_dept'),
    path('payroll/unprocessed/<int:dept_id>/timesheet/<int:pk>/', views.payroll_unprocessed_review, name='payroll_unprocessed_review'),
    path('payroll/processed/', views.payroll_processed, name='payroll_processed'),
    path('payroll/processed/employee/<str:employee_id>/', views.payroll_processed_employee, name='payroll_processed_employee'), 
    

]