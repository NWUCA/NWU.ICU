import math
import random
import base64

from django.shortcuts import render
from django.views import View
import requests
from bs4 import BeautifulSoup
from Crypto.Cipher import AES


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


class UnifiedLogin:
    __login_page_url = "http://authserver.nwu.edu.cn/authserver/login"

    def __init__(self):
        self.__session = requests.session()

    def login(self, username, raw_password):
        response = self.__session.get(self.__login_page_url, verify=False)
        ds = BeautifulSoup(response.text, "html.parser")
        lt = ds.select('input[name="lt"]')[0].get('value')
        dllt = ds.select('input[name="dllt"]')[0].get('value')
        execution = ds.select('input[name="execution"]')[0].get('value')
        _eventId = ds.select('input[name="_eventId"]')[0].get('value')
        rm_shown = ds.select('input[name="rmShown"]')[0].get('value')
        pwd_default_encrypt_salt = self.__get_aes_salt(response.text)
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

        response_login = self.__session.post(self.__login_page_url, data=data, verify=False)
        if response_login is not None:
            msg = self.__get_msg(response_login.text)
            if msg == 1:
                return [True, '登陆成功']
                # title_soup = BeautifulSoup(response_login.text, 'html5lib')
                # title = title_soup.find('title')
                # if (title is None) or title.text != '统一身份认证':
                #     return [False, '登录页面错误']
                # else:
                #     # print("登录成功!")
                #     return [True, '登陆成功']
            elif msg == -1:
                # print("登录失败!")
                return [False, '账号或密码错误']
            elif msg == -2:
                # print("需要验证码!")
                return [False, '需要验证码']
        return [False, '网络错误']

    @staticmethod
    def __get_msg(html):
        soup = BeautifulSoup(html, 'html5lib')
        span = soup.select('span[id="msg"]')
        if len(span) == 0:
            return 1
        msg = soup.select('span[id="msg"]')[0].text
        if msg == "您提供的用户名或者密码有误":
            return -1
        elif msg == "无效的验证码":
            return -2
        elif msg == "请输入验证码":
            return -2

    def __get_aes_salt(self, string):
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
