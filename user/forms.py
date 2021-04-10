from crispy_forms.helper import FormHelper
from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label='用户名', max_length=20, required=True)
    password = forms.CharField(
        label='密码', max_length=100, required=True, widget=forms.PasswordInput
    )

    helper = FormHelper()
    helper.form_tag = False
