from django.urls import reverse
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from test_project.common import create_user
from utils.throttle import LoginIPRateThrottle, LoginUsernameRateThrottle


class AuthenticationSecurityTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.original_ip_rate = LoginIPRateThrottle.rate
        self.original_username_rate = LoginUsernameRateThrottle.rate

    def tearDown(self):
        LoginIPRateThrottle.rate = self.original_ip_rate
        LoginUsernameRateThrottle.rate = self.original_username_rate
        cache.clear()

    def test_csrf_cookie_is_required_for_login(self):
        client = APIClient(enforce_csrf_checks=True)
        login_url = reverse('api:login')
        response = client.post(login_url, {
            'username': 'missing_user',
            'password': 'wrong_password',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        csrf_response = client.get(reverse('api:csrf-token'))
        csrf_token = csrf_response.cookies['csrftoken'].value
        response = client.post(
            login_url,
            {'username': 'missing_user', 'password': 'wrong_password'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_local_frontend_origins_are_trusted_for_login(self):
        login_url = reverse('api:login')

        for origin in ('http://localhost:5173', 'http://127.0.0.1:5173'):
            with self.subTest(origin=origin):
                client = APIClient(enforce_csrf_checks=True)
                csrf_response = client.get(reverse('api:csrf-token'))
                csrf_token = csrf_response.cookies['csrftoken'].value
                response = client.post(
                    login_url,
                    {'username': 'missing_user', 'password': 'wrong_password'},
                    format='json',
                    HTTP_X_CSRFTOKEN=csrf_token,
                    HTTP_ORIGIN=origin,
                )
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_csrf_cookie_is_required_for_authenticated_profile_update(self):
        client = APIClient(enforce_csrf_checks=True)
        user = create_user(is_active=True)
        client.force_login(user)
        profile_url = reverse('api:my_profile')

        response = client.post(profile_url, {'nickname': 'changed'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        csrf_response = client.get(reverse('api:csrf-token'))
        csrf_token = csrf_response.cookies['csrftoken'].value
        response = client.post(
            profile_url,
            {'nickname': 'changed'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unknown_user_and_wrong_password_have_same_response(self):
        create_user(is_active=True)
        login_url = reverse('api:login')
        missing_response = self.client.post(login_url, {
            'username': 'missing_user',
            'password': 'wrong_password',
        }, format='json')
        wrong_password_response = self.client.post(login_url, {
            'username': 'test_user',
            'password': 'wrong_password',
        }, format='json')

        self.assertEqual(missing_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(wrong_password_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(missing_response.data['errors'], wrong_password_response.data['errors'])

    def test_login_attempts_are_rate_limited_by_ip_and_username(self):
        LoginIPRateThrottle.rate = '2/minute'
        LoginUsernameRateThrottle.rate = '2/minute'
        login_data = {
            'username': 'rate_limited_user',
            'password': 'wrong_password',
        }

        first_response = self.client.post(reverse('api:login'), login_data, format='json')
        second_response = self.client.post(reverse('api:login'), login_data, format='json')
        third_response = self.client.post(reverse('api:login'), login_data, format='json')

        self.assertEqual(first_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(second_response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(third_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_ip_limit_applies_across_different_usernames(self):
        LoginIPRateThrottle.rate = '2/minute'
        LoginUsernameRateThrottle.rate = '100/minute'
        login_url = reverse('api:login')

        responses = [
            self.client.post(
                login_url,
                {'username': f'missing_user_{index}', 'password': 'wrong_password'},
                format='json',
            )
            for index in range(3)
        ]

        self.assertEqual(responses[0].status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(responses[1].status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(responses[2].status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_username_limit_is_case_insensitive_and_applies_across_ips(self):
        LoginIPRateThrottle.rate = '100/minute'
        LoginUsernameRateThrottle.rate = '2/minute'
        login_url = reverse('api:login')
        attempts = (
            ('Rate_Limited_User', '192.0.2.1'),
            ('rate_limited_user', '192.0.2.2'),
            (' RATE_LIMITED_USER ', '192.0.2.3'),
        )

        responses = [
            APIClient().post(
                login_url,
                {'username': username, 'password': 'wrong_password'},
                format='json',
                REMOTE_ADDR=ip_address,
            )
            for username, ip_address in attempts
        ]

        self.assertEqual(responses[0].status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(responses[1].status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(responses[2].status_code, status.HTTP_429_TOO_MANY_REQUESTS)
