import base64
import logging
import pickle
import re
from collections import namedtuple
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils.crypto import get_random_string
from django.views import View

from user.models import User

logger = logging.getLogger(__name__)
LoginResult = namedtuple('LoginResult', 'success msg name cookies')


def unified_login(username, raw_password):
    login_page_url = "http://authserver.nwu.edu.cn/authserver/login"
    session = requests.session()
    try:
        response = session.get(login_page_url, timeout=5)
    except requests.exceptions.ConnectionError:
        return LoginResult(False, '连接统一身份认证服务失败, 请稍后重试..', None, None)

    ds = BeautifulSoup(response.text, "html.parser")
    if 'IP被冻结' in ds.text:
        return LoginResult(False, '我们的服务器 IP 被统一身份认证冻结, 请稍后重试..', None, None)

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


def handle_login_error(request, msg):
    messages.error(request, msg)
    if '验证码' in msg:
        messages.error(
            request,
            '请手动使用统一身份认证登录一次, 入口在<a target="_blank" '
            'href="http://authserver.nwu.edu.cn">这里'
            f'<img src="{settings.STATIC_URL}img/box-arrow-up-right.svg" '
            f'alt="authserver"></a>',
            extra_tags='safe',
        )


class Login(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return render(request, 'login.html')
        else:
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else '/')

    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']
        success, msg, name, cookies = unified_login(username, password)
        logger.info(f'{name} 认证状态:{success}-{msg}')
        if success:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = User.objects.create(
                    username=username,
                    name=name,
                    cookie=pickle.dumps(cookies),
                    cookie_last_update=datetime.now(),
                )
            login(request, user)
            messages.add_message(request, messages.SUCCESS, '登录成功')
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else '/')
        else:
            handle_login_error(request, msg)
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
            handle_login_error(request, msg)
        return redirect(redirect_url)
