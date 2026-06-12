from django.urls import path 
from . import views

urlpatterns = [
    path('timesheet/new/', views.new_timesheet, name='new_timesheet'),
    path('timesheet/<int:pk>/', views.add_entry, name='add_entry'),
    path('supervisor/inbox/', views.approval_inbox, name='approval_inbox'),
    path('supervisor/review/<int:pk>/', views.review_timesheet, name='review_timesheet'),

]
