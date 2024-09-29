from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


@override_settings(DEBUG=True)
class LoginTests(APITestCase):
    def setUp(self):
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
        self.login_url = reverse('api:login')
        self.logout_url = reverse('api:logout')
        self.active_url = reverse('api:active')

    def create_account_without_active(self):
        response = self.client.post(self.register_url, self.register_data, format='json')
        return response.data['contents']['token']

    def create_account_with_active(self):
        token = self.create_account_without_active()
        response = self.client.get(self.register_url + "?token=" + token)

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
