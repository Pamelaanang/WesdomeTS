from django.urls import path 
from . import views

urlpatterns = [
    path('timesheet/new/', views.new_timesheet, name='new_timesheet'),
    path('timesheet/<int:pk>/', views.add_entry, name='add_entry'),
    path('supervisor/inbox/', views.approval_inbox, name='approval_inbox'),
    path('supervisor/review/<int:pk>/', views.review_timesheet, name='review_timesheet'),
    path('payroll/unprocessed/', views.payroll_unprocessed, name='payroll_unprocessed'),
    path('payroll/unprocessed/<int:dept_id>/', views.payroll_unprocessed_dept, name='payroll_unprocessed_dept'),
    path('payroll/unprocessed/<int:dept_id>/timesheet/<int:pk>/', views.payroll_unprocessed_review, name='payroll_unprocessed_review'),
    # path('payroll/departments/', views.payroll_departments, name='payroll_departments'),
    # path('payroll/departments/<int:dept_id>/', views.payroll_department_details, name='payroll_department_details'),
    # path('payroll/submissions/<int:dept_id>/timesheet/<int:pk>/', views.payroll_review_timesheet, name='payroll_review_timesheet'),

]