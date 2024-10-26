from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from test_project.common import user_info, create_user, login_user
from utils.constants import errcode_dict


@override_settings(DEBUG=True)
class PasswordResetViewTests(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(is_active=True)
        self.user_info_dict = user_info()
        self.profile_url = reverse('api:profile')

    def test_user_profile(self):
        login_user(self.client, self.user_info_dict)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['contents']['username'], self.user_info_dict['username'])
        self.assertEqual(response.data['contents']['email'], self.user_info_dict['email'])
        self.assertEqual(response.data['contents']['nickname'], self.user_info_dict['nickname'])

    def test_update_profile(self):
        login_user(self.client, self.user_info_dict)
        new_user_info_dict = {"username": 'new_username',
                              "nickname": 'new_nickname',
                              "bio": 'new_bio',
                              }
        response = self.client.post(self.profile_url, new_user_info_dict, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, new_user_info_dict['username'])
        self.assertEqual(self.user.nickname, new_user_info_dict['nickname'])
        self.assertEqual(self.user.bio, new_user_info_dict['bio'])

    def test_update_profile_with_wrong_avatar_uuid(self):
        login_user(self.client, self.user_info_dict)
        new_user_info_dict = {"username": 'new_username',
                              "nickname": 'new_nickname',
                              "bio": 'new_bio',
                              'avatar': 'wrong_uuid'
                              }
        response = self.client.post(self.profile_url, new_user_info_dict, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('avatar', response.data['errors'][-1]['field'])
        self.assertIn('avatar_uuid_error', response.data['errors'][-1]['err_code'])
        self.assertEqual(errcode_dict['avatar_uuid_error'], response.data['errors'][-1]['err_msg'])
