from django import forms
from django.contrib.auth.forms import AuthenticationForm


class UserLoginForm(AuthenticationForm):
    username = forms.CharField(
        label = "Enter Payroll ID",
        max_length=255,
        widget = forms.TextInput(attrs={
            'placeholder': '123456',
            'class': 'w-full bg-transparent outline-none border-none px-4'
            })
    )
    password = forms.CharField(
        label = "Enter Password",
        widget = forms.PasswordInput(attrs={
            'placeholder': 'Password',
            'class': 'w-full bg-transparent outline-none border-none px-4'
            })
    )