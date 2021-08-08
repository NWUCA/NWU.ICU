import base64
import json
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

from .forms import LoginForm

logger = logging.getLogger(__name__)
LoginResult = namedtuple('LoginResult', 'success msg name cookies')


def unified_login(username, raw_password):
    # login_page_url = "http://authserver.nwu.edu.cn/authserver/login"
    login_page_url = (
        "http://authserver.nwu.edu.cn/authserver/login?service=https://a"
        "pp.nwu.edu.cn/a_nwu/api/sso"
        "/cas?redirect=https://app.nwu.edu.cn/site/ncov/dailyup&from=wap"
    )
    i = 0  # 防止上游崩溃 导致无限重试
    while True:
        i = i + 1
        if i == 10:
            return LoginResult(False, '连接统一身份认证服务失败, 请稍后重试..', None, None)
        session = requests.session()
        try:
            response = session.get(login_page_url, timeout=5)
            if response.status_code != 200:
                raise requests.exceptions.ConnectionError
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
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
        # 如果正确的获取到了cookie(也就是没有进入404界面),
        # 那么最终登录302到的网址就是https://app.nwu.edu.cn/site/ncov/dailyup,
        # 如果不是, 则说明密码错误/有验证码/学校的垃圾系统又给你转到了404然而status却等于200的界面
        if response_login.url == 'https://app.nwu.edu.cn/site/ncov/dailyup':
            break  # 这就证明获取到了正确的cookie, redirect到了晨午检填报地址
        else:
            soup = BeautifulSoup(response_login.text, 'html.parser')
            try:
                span = soup.select('span[id="msg"]')
            except IndexError:
                return LoginResult(False, '未知错误, 请尝试重新登录', None, None)
            # 分析一下是否是密码错误or验证码
            try:
                span = span[0].text
                if '验证码' in span or '有误' in span:
                    return LoginResult(False, span, None, None)
            except IndexError:
                continue
    if response_login is not None:
        userinfo_get = session.get('https://app.nwu.edu.cn/ncov/wap/open-report/index')
        # 这里存放的是上一次填报的json信息, 即使之前没有填报也会有realname的信息
        try:
            userinfo = json.loads(userinfo_get.text)
            name = userinfo['d']['userinfo']['realname']
        except IndexError:
            log_dir = settings.BASE_DIR / 'logs'
            log_dir.mkdir(exist_ok=True)
            logger.error('获取个人信息失败')
            with open(log_dir / f'{username}-{datetime.now()}.html', 'wb') as f:
                f.write(response_login.content)
            return LoginResult(False, '获取个人信息失败, 请稍后重试..', None, None)
        for cookie in session.cookies:
            cookie.expires = None
        return LoginResult(True, '登陆成功', name, session.cookies)
    return LoginResult(False, '网络错误', None, None)


def handle_login_error(request, msg):
    messages.error(request, msg)
    if '验证码' in msg or '初始密码' in msg:
        messages.error(
            request,
            '需要输入验证码, 解决方案: 请手动使用统一身份认证登录一次, 入口在<a target="_blank" '
            'href="http://authserver.nwu.edu.cn">这里'
            '<i class="bi bi-box-arrow-up-right"></i></a>',
            extra_tags='safe',
        )


class Login(View):
    def render_login_page(self, request):
        return render(request, 'login.html', {'login_form': LoginForm()})

    def get(self, request):
        if not request.user.is_authenticated:
            return self.render_login_page(request)
        else:
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else '/')

    def post(self, request):
        form = LoginForm(request.POST)
        username = request.POST['username']
        password = request.POST['password']
        if form.is_valid():
            success, msg, name, cookies = unified_login(username, password)
            logger.info(f'{name} 认证状态:{success}-{msg}')
            if success:
                try:
                    user = User.objects.get(username=username)
                    user.cookie = pickle.dumps(cookies)
                    user.cookie_last_update = datetime.now()
                    user.save()
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
                return self.render_login_page(request)
        else:
            return self.render_login_page(request)


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
