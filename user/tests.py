from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


@override_settings(DEBUG=True)
class RegisterTests(APITestCase):
    def setUp(self):
        self.register_data = {
            "username": "testUser",
            "password": "testPassword1",
            "email": "asd@exapmple.com",
            "captcha_key": "2b4c32b83a911018fdda8b5ce0ebf8ae3f7a81fd",
            "captcha_value": "PASSED"
        }
        self.url = reverse('api:register')

    def test_create_account_password_must_contain_one_number(self):
        register_data_copy = self.register_data.copy()
        for password in ['password', 'PASSWORD', 'passWORD', '12345678', '123password', '123PASSWORD']:
            register_data_copy['password'] = password
            response = self.client.post(self.url, register_data_copy, format='json')
            self.assertIn("密码必须同时包含大写字母, 小写字母, 数字", response.data['errors']['password'])
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_password_not_compliant_length(self):
        register_data_copy = self.register_data.copy()
        for password in ['1pA', 'Thequickbrownfoxjumpedoverthelazydog']:
            register_data_copy['password'] = password
            response = self.client.post(self.url, register_data_copy, format='json')
            self.assertIn("密码长度必须在8-30之间", response.data['errors']['password'])
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_college_email(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["email"] = "test@" + settings.UNIVERSITY_MAIL_SUFFIX
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"注册时不可使用{settings.UNIVERSITY_CHINESE_NAME}邮箱",
                      response.data['errors']['email'])

    def test_create_account_with_correct_info(self):
        response = self.client.post(self.url, self.register_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual("已发送邮件", response.data['message'])

    def test_create_account_with_exist_email(self):
        self.client.post(self.url, self.register_data, format='json')
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] += 'copy'
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("此邮箱已被注册", response.data['errors']['email'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_exist_username(self):
        self.client.post(self.url, self.register_data, format='json')
        register_data_copy = self.register_data.copy()
        register_data_copy["email"] = 'copy' + register_data_copy["email"]
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("已存在一位使用该名字的用户", response.data['errors']['username'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_illegal_username(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] = 'asdasdas!d'
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("用户名只能包含字母、数字和下划线", response.data['errors']['username'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_illegal_username_length(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] = register_data_copy["username"] * 20
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("用户名长度必须在8到29个字符之间", response.data['errors']['username'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
