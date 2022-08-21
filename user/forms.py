from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label='用户名', max_length=20, required=True)
    password = forms.CharField(label='密码', max_length=100, required=True, widget=forms.PasswordInput)
    captcha = forms.CharField(label='验证码', max_length=10, required=True)
