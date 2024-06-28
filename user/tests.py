from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from user.models import User


class LoginTestCase(APITestCase):
    def setUp(self):
        self.url = reverse('login')  # 假设 URL 名称为 'login'
        self.user = User.objects.create_user(username='testuser', password='testpassword')
        self.client = APIClient()

    def test_login_success(self):
        data = {
            'username': 'testuser',
            'password': 'testpassword'
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('sessionid', response.cookies)
        self.assertEqual(response.data['detail'], 'Login successful')

    def test_login_failure_invalid_credentials(self):
        data = {
            'username': 'testuser',
            'password': 'wrongpassword'
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['detail'], 'Authentication failed.')

    def test_login_failure_invalid_data(self):
        data = {
            'username': '',
            'password': ''
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# def test_need_to_set_nickname(user, logged_in_client):
#     user.nickname = ""
#     user.save()
#     r = logged_in_client.get('/', follow=True)
#     assert r.redirect_chain[0][0].endswith('/settings/')
#
#     r = logged_in_client.post('/settings/', data={"nickname": "alice"})
#     assert r.status_code == 302
#     r = logged_in_client.get('/')
#     assert r.status_code == 200
