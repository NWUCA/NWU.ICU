import base64
import logging
import pickle
import re
from collections import namedtuple
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from bs4 import BeautifulSoup
from django.contrib import messages
from django.contrib.auth import login, logout
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.crypto import get_random_string
from django.views import View
from requests.utils import dict_from_cookiejar

from settings.log import upload_pastebin_and_send_to_tg
from user.models import User
from .forms import LoginForm
from .forms import PasswordResetForm

logger = logging.getLogger(__name__)
LoginResult = namedtuple('LoginResult', 'success msg name cookies')

AUTH_SERVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36'
}


def unified_login(username, raw_password, captcha, captcha_cookies):
    login_page_url = "https://authserver.nwu.edu.cn/authserver/login"
    session = requests.sessions.Session()
    # 欺骗学校的防火墙
    session.headers.update(AUTH_SERVER_HEADERS)
    session.cookies.update(captcha_cookies)
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
        "captchaResponse": captcha,
    }

    response_login = session.post(login_page_url, data=data)

    if response_login is not None:
        soup = BeautifulSoup(response_login.text, 'html.parser')

        if '踢出会话' in response_login.text:
            response_login = session.post(
                login_page_url,
                data={
                    'execution': soup.find(id='continue').find(attrs={"name": "execution"})['value'],
                    '_eventId': 'continue',
                },
            )
            soup = BeautifulSoup(response_login.text, 'html.parser')

        if soup.find(id='improveInfoForm'):
            return LoginResult(False, '您的密码仍为初始密码, 请更新您的密码后重试..', None, None)

        span = soup.select('span[id="msg"]')
        if len(span) == 0:
            try:
                name = soup.find(class_='auth_username').span.span.text.strip()
            except AttributeError:
                upload_pastebin_and_send_to_tg(response_login.text)
                return LoginResult(False, '获取个人信息失败, 请稍后重试..', None, None)

            return LoginResult(True, '登陆成功', name, session.cookies)
        else:
            msg = span[0].text
            return LoginResult(False, msg, None, None)
    return LoginResult(False, '网络错误', None, None)


def handle_login_error(request, msg):
    messages.error(request, msg)
    if '初始密码' in msg:
        messages.error(
            request,
            '请手动使用统一身份认证登录一次, 入口在<a target="_blank" '
            'href="http://authserver.nwu.edu.cn">这里'
            '<i class="bi bi-box-arrow-up-right"></i></a>',
            extra_tags='safe',
        )


def register(request):
    return render(request, 'register.html')


class PasswordReset(View):
    def render_password_reset_page(self, request):
        return render(request, 'password_reset.html')

    def get(self, request):
        form = PasswordResetForm()
        return render(request, 'password_reset.html', {'form': form})

    def post(self, request):
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            messages.success(request, "修改成功, 请使用新密码登录")
            return redirect('login')
        else:
            # 提取 email 数据并重新初始化表单
            email = request.POST.get('email', '')
            form = PasswordResetForm(initial={'email': email})
            messages.error(request, "验证码输入错误, 请仔细查看后输入")
            return render(request, 'password_reset.html', {'form': form})


class Register(View):
    def get(self, request):
        return render(request, 'register.html')


class CAPTCHA(View):
    def get(self, request):
        captcha_url = "https://authserver.nwu.edu.cn/authserver/captcha.html"
        r = requests.get(captcha_url, headers=AUTH_SERVER_HEADERS)
        request.session['captcha_cookies'] = dict_from_cookiejar(r.cookies)
        return HttpResponse(r.content, headers={'Content-Type': 'image/jpeg'})


class Login(View):
    @staticmethod
    def render_login_page(request):
        return render(request, 'login.html', {'login_form': LoginForm()})

    def get(self, request):
        if not request.user.is_authenticated:
            return self.render_login_page(request)
        else:
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else '/')

    def post(self, request):
        form = LoginForm(request.POST)

        if not form.is_valid():
            messages.error(request, "登陆表单异常")
            return self.render_login_page(request)

        if not (captcha_cookies := request.session.get('captcha_cookies')):
            messages.error(request, "未获取到验证码, 请刷新重试")
            return self.render_login_page(request)

        username = form.cleaned_data['username']
        password = form.cleaned_data['password']
        captcha = form.cleaned_data['captcha']
        success, msg, name, cookies = unified_login(username, password, captcha, captcha_cookies)
        logger.info(f'{name} 认证状态:{success}-{msg}')
        if '获取个人信息失败' in msg:
            logger.error('获取个人信息失败', extra={'request': request})
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
                    nickname="",
                )
            login(request, user)
            messages.add_message(request, messages.SUCCESS, '登录成功')
            next_url = request.GET.get('next')
            return redirect(next_url if next_url else '/')
        else:
            handle_login_error(request, msg)
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
