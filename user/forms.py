from captcha.fields import CaptchaField
from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label='用户名', max_length=20, required=True,
                               widget=forms.TextInput(attrs={'placeholder': '请输入用户名'}),
                               error_messages={
                                   'required': '用户名不能为空',
                                   'max_length': '用户名不能超过150个字符',
                               })
    password = forms.CharField(label='密码', max_length=100, required=True,
                               widget=forms.PasswordInput(attrs={'placeholder': '请输入密码'}),
                               error_messages={
                                   'required': '密码不能为空',
                               })


class PasswordResetForm(forms.Form):
    email = forms.EmailField(label='电子邮件', required=True, widget=forms.EmailInput(attrs={
        'class': 'input',
        'placeholder': '请输入注册时的电子邮件'
    }))
    captcha = CaptchaField()
