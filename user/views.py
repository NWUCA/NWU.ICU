import base64
import re
import pickle
from datetime import datetime
from collections import namedtuple

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


LoginResult = namedtuple('LoginResult', 'success msg name cookies')


def unified_login(username, raw_password):
    login_page_url = "http://authserver.nwu.edu.cn/authserver/login"
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

            # 获取 app.nwu.edu.cn 域下的 cookies
            session.get('https://app.nwu.edu.cn/uc/wap/login')
            return LoginResult(True, '登陆成功', name, session.cookies)
        else:
            msg = span[0].text
            return LoginResult(False, msg, None, None)  # TODO: 需要验证码时的处理
    return LoginResult(False, '网络错误', None, None)


class Login(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']
        success, msg, name, cookies = unified_login(username, password)
        print(success, msg, name)  # TODO: log format
        if success:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = User.objects.create(
                    username=username,
                    name=name,
                    cookie=pickle.dumps(cookies),
                    cookie_last_update=datetime.now()
                )
            login(request, user)
            messages.add_message(request, messages.SUCCESS, '登录成功')
            return redirect('/')
        else:
            messages.error(request, msg)
            if '验证码' in msg:
                messages.error(request, '请手动使用统一身份认证登录一次')
            return render(request, 'login.html')


class Logout(View):
    def get(self, request):
        logout(request)
        messages.add_message(request, messages.SUCCESS, '注销成功')
        return redirect('/')


class RefreshCookies(View):
    def post(self, request):
        user = request.user
        password = request.POST['password']
        redirect_url = request.POST.get('redirect')  # FIXME: 是否为最优的方案?
        success, msg, name, cookies = unified_login(user.username, password)
        if success:
            user.cookie = pickle.dumps(cookies)
            user.cookie_last_update = datetime.now()
            user.save()
            messages.success(request, '刷新 Cookies 成功, 请重新开启填报')
        else:
            messages.error(request, msg)
            if '验证码' in msg:
                messages.error(request, '请手动使用统一身份认证登录一次')
        return redirect(redirect_url)
