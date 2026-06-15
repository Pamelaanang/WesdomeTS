from django.urls import path
from users import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('users/', views.user_list_view, name='user_list'),
    path('users/reset/<str:employeeid>/', views.generate_password, name='reset_password'),
    path('users/replace/<str:employeeid>/', views.replace_employee, name='replace_employee'),
    path('users/add/', views.add_employee, name='add_employee'),
    path('password_reset/', views.password_reset_view, name='password_reset'),
    path('profile/', views.profile, name='profile'),
    path('profile/upload-photo/', views.upload_profile_photo, name='upload_profile_photo'),

]