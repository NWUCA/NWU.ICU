import base64
import re

from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import login, logout
from django.contrib import messages
from django.utils.crypto import get_random_string
import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from user.models import User


def unified_login(username, raw_password):
    login_page_url = "https://authserver.nwu.edu.cn/authserver/login"
    session = requests.session()
    response = session.get(login_page_url)
    ds = BeautifulSoup(response.text, "html.parser")
    lt = ds.select('input[name="lt"]')[0].get('value')
    dllt = ds.select('input[name="dllt"]')[0].get('value')
    execution = ds.select('input[name="execution"]')[0].get('value')
    _eventId = ds.select('input[name="_eventId"]')[0].get('value')
    rm_shown = ds.select('input[name="rmShown"]')[0].get('value')

    # key 被单独写在一个 <script> 标签里
    aes_key = re.search('var pwdDefaultEncryptSalt = "(.*)";', response.text)[1]

    raw_password_byte = (get_random_string(64) + raw_password).encode()  # 随机字符串为统一身份认证的行为
    raw_password_byte = pad(raw_password_byte, AES.block_size)
    # PyCryptodome 提供的 iv 似乎会包含统一身份认证不会识别的字符, 导致返回用户名或密码错误
    cipher = AES.new(aes_key.encode(), AES.MODE_CBC, get_random_string(16).encode())
    password = base64.b64encode(cipher.encrypt(raw_password_byte))

    data = {
        "_eventId": _eventId,
        "dllt": dllt,
        "execution": execution,
        "lt": lt,
        "password": password,
        "rmShown": rm_shown,
        "username": username,
    }

    response_login = session.post(login_page_url, data=data)
    if response_login is not None:
        soup = BeautifulSoup(response_login.text, 'html.parser')
        span = soup.select('span[id="msg"]')
        if len(span) == 0:
            name = soup.find(class_='auth_username').span.span.text.strip()
            return [True, '登陆成功', name]
        else:
            msg = span[0].text
            return [False, msg, None]  # TODO: 需要验证码时的处理
    return [False, '网络错误', None]


class Login(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']
        success, msg, name = unified_login(username, password)
        print(success, msg, name)  # TODO: log format
        if success:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = User.objects.create(username=username, name=name)
            login(request, user)
            messages.add_message(request, messages.SUCCESS, '登录成功')
            return redirect('/')
        else:
            messages.add_message(request, messages.ERROR, msg)
            return render(request, 'login.html')


class Logout(View):
    def get(self, request):
        logout(request)
        messages.add_message(request, messages.SUCCESS, '注销成功')
        return redirect('/')
