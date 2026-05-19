from django import forms
from django.contrib.auth.forms import AuthenticationForm


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        label = "Payroll ID",
        max_length=255,
        widget = forms.TextInput(attrs={
            'placeholder': 'Enter Payroll ID',
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none'
            })
    )
    password = forms.CharField(
        label = "Password",
        widget = forms.PasswordInput(attrs={
            'placeholder': 'Enter Your Password',
            'class': 'w-full px-4 py-2 border rounded-lg focus:outline-none'
            })
    )