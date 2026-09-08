from copy import deepcopy

from django.conf import settings
from django.test import override_settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


@override_settings(DEBUG=True)
class LoginTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.register_data = {
            "username": "testUser",
            "password": "testPassword1",
            "email": "asd@exapmple.com",
            "captcha_key": "2b4c32b83a911018fdda8b5ce0ebf8ae3f7a81fd",
            "captcha_value": "PASSED"
        }
        self.login_data = {
            'username': self.register_data['username'],
            'password': self.register_data['password'],
        }
        self.register_url = reverse('api:register')
        self.activation_url = reverse('api:register-activate')
        self.login_url = reverse('api:login')
        self.logout_url = reverse('api:logout')
        self.active_url = reverse('api:active')

    def create_account_without_active(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        return response.data['contents']['token']

    def create_account_with_active(self):
        token = self.create_account_without_active()
        self.client.post(self.activation_url, {'token': token}, format='json')

    def test_login_without_active(self):
        self.create_account_without_active()
        response = self.client.post(self.login_url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_success(self):
        self.create_account_with_active()
        response = self.client.post(self.login_url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_login_with_wrong_password(self):
        self.create_account_with_active()
        login_data_copy = self.login_data.copy()
        login_data_copy["password"] = login_data_copy["password"] + "wrong"
        response = self.client.post(self.login_url, login_data_copy, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_after_logged_in(self):
        self.create_account_with_active()
        self.client.post(self.login_url, self.login_data, format='json')
        response = self.client.post(self.login_url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_when_login(self):
        self.create_account_with_active()
        self.client.post(self.login_url, self.login_data, format='json')
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_when_not_login(self):
        response = self.client.post(self.logout_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_login_without_active_resend_active_email(self):
        self.create_account_without_active()
        response = self.client.post(self.active_url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_active_user_when_activated(self):
        self.create_account_with_active()
        response = self.client.post(self.active_url, self.login_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_active_user_when_password_wrong(self):
        self.create_account_without_active()
        login_data_copy = self.login_data.copy()
        login_data_copy["password"] = login_data_copy["password"] + "wrong"
        response = self.client.post(self.active_url, login_data_copy, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_active_account_with_wrong_token(self):
        token = self.create_account_without_active()
        response = self.client.post(
            self.activation_url, {'token': token[::-1]}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_api_and_admin_login_share_username_throttle(self):
        config = deepcopy(settings.API_RATE_LIMITS)
        config['login'].update({
            'captcha_after_failures': 5,
            'emergency_ip': '100/minute',
        })
        self.create_account_with_active()
        wrong_login = {**self.login_data, 'password': 'wrong'}
        with override_settings(API_RATE_LIMITS=config):
            for _ in range(4):
                self.client.post(self.login_url, wrong_login, format='json')

            admin_page = self.client.get('/admin/login/')
            csrf_token = admin_page.cookies['csrftoken'].value
            fifth = self.client.post(
                '/admin/login/',
                wrong_login,
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            sixth = self.client.post(
                '/admin/login/',
                wrong_login,
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertNotEqual(fifth.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(sixth.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
