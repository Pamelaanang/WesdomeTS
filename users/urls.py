from django.urls import path
from users import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('home/', views.home_view, name='home'),
    path('users/', views.user_list_view, name='user_list'),
    path('users/reset/<str:employeeid>/', views.reset_password_view, name='reset_password'),
    path('password_reset/', views.password_reset_view, name='password_reset'),
]