from django import forms
from captcha.fields import CaptchaField


class LoginForm(forms.Form):
    username = forms.CharField(label='用户名', max_length=20, required=True)
    password = forms.CharField(label='密码', max_length=100, required=True, widget=forms.PasswordInput)
    captcha = forms.CharField(label='验证码', max_length=10, required=True)


class PasswordResetForm(forms.Form):
    email = forms.EmailField(label='电子邮件', required=True, widget=forms.EmailInput(attrs={
        'class': 'input',
        'placeholder': '请输入注册时的电子邮件'
    }))
    captcha = CaptchaField()
