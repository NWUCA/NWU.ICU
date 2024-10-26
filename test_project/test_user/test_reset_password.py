from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from test_project.common import user_info, create_user, login_user, check_login_status
from utils.constants import errcode_dict


@override_settings(DEBUG=True)
class PasswordResetViewTests(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.reset_password_data = {'email': user_info()['email'],
                                    'captcha_key': 'test',
                                    'captcha_value': 'test'}
        self.reset_password_data_when_logged_in_data = {
            "old_password": user_info()['password'],
            "new_password": user_info()['password'],
            "confirm_password": user_info()['password'],
            "captcha_key": "test",
            "captcha_value": "passed"
        }
        self.user = create_user(is_active=True)
        self.reset_url = reverse('api:reset')

    def test_password_reset_via_username_email_success(self):
        response = self.client.post(self.reset_url, self.reset_password_data, format='json')
        self.assertEqual(response.status_code, 200)

    def test_password_reset_via_username_email_not_exist(self):
        self.reset_password_data['email'] = 'another@example.com'
        response = self.client.post(self.reset_url, self.reset_password_data, format='json')
        self.assertEqual(response.status_code, 400)

    def test_password_reset_via_email_token(self):
        token = self.client.post(self.reset_url, self.reset_password_data, format='json').data['contents']['token']
        response = self.client.get(reverse('api:mail-reset', args=[token]))
        self.assertEqual(response.status_code, 200)

    def test_password_reset_via_email_wrong_token(self):
        token = self.client.post(self.reset_url, self.reset_password_data, format='json').data['contents']['token']
        response = self.client.get(reverse('api:mail-reset', args=[token[::-1]]))
        self.assertEqual(response.status_code, 400)

    def test_password_reset_success(self):
        token = self.client.post(self.reset_url, self.reset_password_data, format='json').data['contents']['token']
        new_password = "123345aaaA"
        reset_new_password_data = {"new_password": new_password,
                                   "confirm_password": new_password,
                                   "captcha_key": "12",
                                   "captcha_value": "123"}
        response = self.client.post(reverse('api:mail-reset', args=[token]), reset_new_password_data, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))

    def test_reset_password_via_old_password_when_not_login(self):
        self.assertFalse(check_login_status(self.client))  # 强制登出
        self.reset_password_data_when_logged_in_data['new_password'] = user_info()['password'] + 'extra'
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertIn('login', response.data['errors'][-1]['field'])
        self.assertIn('not_login', response.data['errors'][-1]['err_code'])

    def test_reset_password_logged_in_use_same_password(self):
        login_user(self.client)
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertIn('password', response.data['errors'][-1]['field'])
        self.assertIn('password_re_equal_old', response.data['errors'][-1]['err_code'])
        self.assertEqual(errcode_dict['password_re_equal_old'], response.data['errors'][-1]['err_msg'])
        self.assertTrue(check_login_status(self.client))

    def test_reset_password_logged_in_use_wrong_old_password(self):
        login_user(self.client)
        self.reset_password_data_when_logged_in_data['old_password'] = self.reset_password_data_when_logged_in_data[
                                                                           'old_password'] + 'wrong'
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertIn('password', response.data['errors'][-1]['field'])
        self.assertIn('password_old_not_true', response.data['errors'][-1]['err_code'])
        self.assertEqual(errcode_dict['password_old_not_true'], response.data['errors'][-1]['err_msg'])
        self.assertTrue(check_login_status(self.client))

    def test_reset_password_logged_user_different_new_password(self):
        login_user(self.client)
        self.reset_password_data_when_logged_in_data['new_password'] = user_info()['password'] + 'extra1'
        self.reset_password_data_when_logged_in_data['confirm_password'] = user_info()['password'] + 'extra2'
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertIn('password', response.data['errors'][-1]['field'])
        self.assertIn('password_re_not_consistent', response.data['errors'][-1]['err_code'])
        self.assertEqual(errcode_dict['password_re_not_consistent'], response.data['errors'][-1]['err_msg'])
        self.assertTrue(check_login_status(self.client))

    def test_reset_password_logged_invalid_new_password(self):
        login_user(self.client)
        self.reset_password_data_when_logged_in_data['new_password'] = user_info()['password'] + 'extra'
        self.reset_password_data_when_logged_in_data['confirm_password'] = self.reset_password_data_when_logged_in_data[
            'new_password']
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertIn('password', response.data['errors'][-1]['field'])
        self.assertIn('password_invalid_char', response.data['errors'][-1]['err_code'])
        self.assertEqual(errcode_dict['password_invalid_char'], response.data['errors'][-1]['err_msg'])
        self.assertTrue(check_login_status(self.client))

    def test_reset_password_logged_success(self):
        login_user(self.client)
        self.reset_password_data_when_logged_in_data['new_password'] = user_info()['password'] + 'extrA1'
        self.reset_password_data_when_logged_in_data['confirm_password'] = self.reset_password_data_when_logged_in_data[
            'new_password']
        response = self.client.post(reverse('api:reset-login'), data=self.reset_password_data_when_logged_in_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(check_login_status(self.client))  # 强制登出
