from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from test_project.common import create_user, login_user


@override_settings(DEBUG=True)
class BindCollegeEmailTest(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(is_active=True)
        self.bind_email = reverse('api:bind-college-email-post')
        self.bind_college_email = {"college_email": "test@" + settings.UNIVERSITY_MAIL_SUFFIX}

    def test_bind_college_email_get_token_success(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        self.assertEqual(response.status_code, 200)

    def test_bind_college_email_with_invalid_email_suffix(self):
        login_user(self.client)
        self.bind_college_email['college_email'] = '123@example.com'
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        self.assertEqual(response.status_code, 400)

    def test_bind_college_email_from_email_wrong_token(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        token = response.data['contents']['token'][::-1]
        response = self.client.get(reverse('api:bind-college-email-get', args=[token]))
        self.assertEqual(response.status_code, 400)

    def test_bind_college_email_from_email_token(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        token = response.data['contents']['token']
        response = self.client.get(reverse('api:bind-college-email-get', args=[token]))
        self.assertEqual(response.status_code, 200)
