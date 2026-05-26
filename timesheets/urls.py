from django.urls import path 
from . import views

urlpatterns = [
    path('timesheet/new/', views.new_timesheet, name='new_timesheet'),
    path('timesheet/<int:pk>/', views.add_entry, name='add_entry'),

]
