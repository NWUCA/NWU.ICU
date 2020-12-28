import math
import random
import base64

from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import login, logout
from django.contrib import messages
import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES

from user.models import User


class AESCipher:
    def __init__(self, key):
        self.key = key.encode()
        self.iv = self.random_string(16).encode()

    def __pad(self, text):
        """填充方式，加密内容必须为16字节的倍数，若不足则使用self.iv进行填充"""
        text_length = len(text)
        amount_to_pad = AES.block_size - (text_length % AES.block_size)
        if amount_to_pad == 0:
            amount_to_pad = AES.block_size
        pad = chr(amount_to_pad)
        return text + pad * amount_to_pad

    def encrypt(self, text):
        """加密"""
        raw = self.random_string(64) + text
        raw = self.__pad(raw).encode()
        cipher = AES.new(self.key, AES.MODE_CBC, self.iv)
        return base64.b64encode(cipher.encrypt(raw))

    @staticmethod
    def random_string(length):
        aes_chars = 'ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678'
        aes_chars_len = len(aes_chars)
        ret_str = ''
        for i in range(0, length):
            ret_str += aes_chars[math.floor(random.random() * aes_chars_len)]
        return ret_str


def unified_login(username, raw_password):
    login_page_url = "http://authserver.nwu.edu.cn/authserver/login"
    session = requests.session()
    response = session.get(login_page_url, verify=False)
    ds = BeautifulSoup(response.text, "html.parser")
    lt = ds.select('input[name="lt"]')[0].get('value')
    dllt = ds.select('input[name="dllt"]')[0].get('value')
    execution = ds.select('input[name="execution"]')[0].get('value')
    _eventId = ds.select('input[name="_eventId"]')[0].get('value')
    rm_shown = ds.select('input[name="rmShown"]')[0].get('value')
    pwd_default_encrypt_salt = __get_aes_salt(response.text)
    pc = AESCipher(pwd_default_encrypt_salt)  # 初始化密钥
    password = pc.encrypt(raw_password)  # 加密
    data = {
        "_eventId": _eventId,
        "dllt": dllt,
        "execution": execution,
        "lt": lt,
        "password": password,
        "rmShown": rm_shown,
        "username": username,
    }

    response_login = session.post(login_page_url, data=data, verify=False)
    if response_login is not None:
        soup = BeautifulSoup(response_login.text, 'html.parser')
        span = soup.select('span[id="msg"]')
        if len(span) == 0:
            success = 1
        else:
            msg = soup.select('span[id="msg"]')[0].text
            if msg == "您提供的用户名或者密码有误":
                success = -1
            elif msg == "无效的验证码":
                success = -2
            elif msg == "请输入验证码":
                success = -2
            else:
                success = -3

        if success == 1:
            name = soup.find(class_='auth_username').span.span.text.strip()
            return [True, '登陆成功', name]
            # title_soup = BeautifulSoup(response_login.text, 'html5lib')
            # title = title_soup.find('title')
            # if (title is None) or title.text != '统一身份认证':
            #     return [False, '登录页面错误']
            # else:
            #     # print("登录成功!")
            #     return [True, '登陆成功']
        elif success == -1:
            # print("登录失败!")
            return [False, '账号或密码错误', None]
        elif success == -2:
            # print("需要验证码!")
            return [False, '需要验证码', None]
    return [False, '网络错误', None]


def __get_aes_salt(string):
    """
    :param string: 登陆界面源码
    :return: 盐值
    """
    t1 = string.split('pwdDefaultEncryptSalt = "')[1]
    t2 = t1.split('"')[0]
    return t2


class Login(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        username = request.POST['username']
        password = request.POST['password']
        success, msg, name = unified_login(username, password)
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
