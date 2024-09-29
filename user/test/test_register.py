from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from common.utils import get_msg_msg


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
        self.dup_username_url = reverse('api:username')

    def test_user_name_duplicate_when_dup(self):
        self.client.post(self.url, self.register_data, format='json')
        response = self.client.post(self.dup_username_url, {"username": self.register_data['username']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_user_name_duplicate_when_not_dup(self):
        response = self.client.post(self.dup_username_url, {"username": self.register_data['username']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_create_account_password_must_contain_one_number(self):
        register_data_copy = self.register_data.copy()
        for password in ['password', 'PASSWORD', 'passWORD', '12345678', '123password', '123PASSWORD']:
            register_data_copy['password'] = password
            response = self.client.post(self.url, register_data_copy, format='json')
            self.assertIn("password_invalid_char", response.data['errors'][0]['err_code'])
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_password_not_compliant_length(self):
        register_data_copy = self.register_data.copy()
        for password in ['1pA', 'Thequickbrownfoxjumpedoverthelazydog']:
            register_data_copy['password'] = password
            response = self.client.post(self.url, register_data_copy, format='json')
            self.assertIn("password_not_match_length", response.data['errors'][0]['err_code'])
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_college_email(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["email"] = "test@" + settings.UNIVERSITY_MAIL_SUFFIX
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"invalid_college_email",
                      response.data['errors'][0]['err_code'])

    def test_create_account_with_correct_info(self):
        response = self.client.post(self.url, self.register_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_msg_msg('has_sent_email'), response.data['message'])

    def test_create_account_with_exist_email(self):
        self.client.post(self.url, self.register_data, format='json')
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] += 'copy'
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("email_duplicate", response.data['errors'][0]['err_code'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_exist_username(self):
        self.client.post(self.url, self.register_data, format='json')
        register_data_copy = self.register_data.copy()
        register_data_copy["email"] = 'copy' + register_data_copy["email"]
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("username_duplicate", response.data['errors'][0]['err_code'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_illegal_username(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] = 'asdasdas!d'
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("username_invalid_char", response.data['errors'][0]['err_code'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_account_with_illegal_username_length(self):
        register_data_copy = self.register_data.copy()
        register_data_copy["username"] = register_data_copy["username"] * 20
        response = self.client.post(self.url, register_data_copy, format='json')
        self.assertIn("username_not_match_length", response.data['errors'][0]['err_code'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(DEBUG=True)
class ActiveTests(APITestCase):
    def setUp(self):
        self.register_data = {
            "username": "testUser",
            "password": "testPassword1",
            "email": "asd@exapmple.com",
            "captcha_key": "2b4c32b83a911018fdda8b5ce0ebf8ae3f7a81fd",
            "captcha_value": "PASSED"
        }
        self.url = reverse('api:register')

    def create_account_with_correct_info(self):
        response = self.client.post(self.url, self.register_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_msg_msg('has_sent_email'), response.data['message'])
        return response.data['contents']['token']

    def test_wrong_token(self):
        response = self.client.get(self.url + '?token=cddi53-499d34fb09b1d8004411c6215f34a8a4')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_correct_token(self):
        token = self.create_account_with_correct_info()
        response = self.client.get(self.url + "?token=" + token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
