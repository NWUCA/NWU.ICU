import copy
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from test_project.common import create_user, login_user
from user.tokens import UserTokenPurpose, issue_user_token


@override_settings(DEBUG=True)
class BindCollegeEmailTest(APITestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = create_user(is_active=True)
        self.bind_email = reverse('api:bind-college-email-bind')
        self.bind_college_email = {"college_email": "test@" + settings.UNIVERSITY_MAIL_SUFFIX}

    def test_resending_bind_email_is_rate_limited(self):
        config = copy.deepcopy(settings.API_RATE_LIMITS)
        config['email'].update({
            'user': '1/minute',
            'address': '10/minute',
        })
        login_user(self.client)

        with override_settings(API_RATE_LIMITS=config):
            first = self.client.post(self.bind_email, self.bind_college_email, format='json')
            second = self.client.post(self.bind_email, self.bind_college_email, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.data['errors'][0]['err_code'], 'too_many_requests')
        self.assertIn('Retry-After', second)

    def test_bind_college_email_get_token_success(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        self.assertEqual(response.status_code, 200)
        token = response.data['contents']['token']
        link_token = parse_qs(
            urlparse(response.data['contents']['link']).fragment
        )['token'][0]
        self.assertEqual(link_token, token)

    def test_bind_college_email_with_invalid_email_suffix(self):
        login_user(self.client)
        self.bind_college_email['college_email'] = '123@example.com'
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        self.assertEqual(response.status_code, 400)

    def test_bind_college_email_from_email_wrong_token(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        token = response.data['contents']['token'][::-1]
        response = self.client.post(
            reverse('api:bind-college-email-verify'), {'token': token}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_bind_college_email_from_email_token(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        token = response.data['contents']['token']
        response = self.client.post(
            reverse('api:bind-college-email-verify'), {'token': token}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.college_email_verified)

        response = self.client.post(
            reverse('api:bind-college-email-verify'), {'token': token}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_bind_token_cannot_reset_password(self):
        login_user(self.client)
        response = self.client.post(self.bind_email, self.bind_college_email, format='json')
        token = response.data['contents']['token']

        response = self.client.post(
            reverse('api:mail-reset-verify'), {'token': token}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_verified_college_email_cannot_be_bound_to_another_user(self):
        self.user.college_email = self.bind_college_email['college_email'].lower()
        self.user.college_email_verified = True
        self.user.save()
        second_user = create_user(
            username='second_user',
            email='second@example.com',
            is_active=True,
        )
        self.client.force_login(second_user)

        response = self.client.post(self.bind_email, {
            'college_email': self.bind_college_email['college_email'].upper(),
        }, format='json')

        self.assertEqual(response.status_code, 400)
        second_user.refresh_from_db()
        self.assertIsNone(second_user.college_email)

    def test_activation_and_reset_tokens_cannot_verify_college_email(self):
        login_user(self.client)
        self.user.college_email = self.bind_college_email['college_email']
        self.user.save(update_fields=('college_email',))

        for purpose in (
                UserTokenPurpose.ACCOUNT_ACTIVATION,
                UserTokenPurpose.PASSWORD_RESET,
        ):
            with self.subTest(purpose=purpose):
                token = issue_user_token(self.user, purpose, email=self.user.email)
                response = self.client.post(
                    reverse('api:bind-college-email-verify'),
                    {'token': token},
                    format='json',
                )
                self.assertEqual(response.status_code, 400)
                self.user.refresh_from_db()
                self.assertFalse(self.user.college_email_verified)

    def test_bind_token_is_scoped_to_authenticated_user(self):
        login_user(self.client)
        token = self.client.post(
            self.bind_email, self.bind_college_email, format='json'
        ).data['contents']['token']
        second_user = create_user(
            username='second_user', email='second@example.com', is_active=True
        )
        self.client.force_login(second_user)

        response = self.client.post(
            reverse('api:bind-college-email-verify'),
            {'token': token},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.college_email_verified)

    def test_requesting_a_new_bind_email_invalidates_previous_token(self):
        login_user(self.client)
        first_token = self.client.post(
            self.bind_email, self.bind_college_email, format='json'
        ).data['contents']['token']
        second_email = {'college_email': 'second@' + settings.UNIVERSITY_MAIL_SUFFIX}
        second_token = self.client.post(
            self.bind_email, second_email, format='json'
        ).data['contents']['token']

        old_response = self.client.post(
            reverse('api:bind-college-email-verify'),
            {'token': first_token},
            format='json',
        )
        new_response = self.client.post(
            reverse('api:bind-college-email-verify'),
            {'token': second_token},
            format='json',
        )

        self.assertEqual(old_response.status_code, 400)
        self.assertEqual(new_response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.college_email, second_email['college_email'])
        self.assertTrue(self.user.college_email_verified)

    def test_email_claimed_after_token_issue_is_rejected_at_verification(self):
        login_user(self.client)
        token = self.client.post(
            self.bind_email, self.bind_college_email, format='json'
        ).data['contents']['token']
        create_user(
            username='second_user',
            email='second@example.com',
            is_active=True,
            college_email=self.bind_college_email['college_email'].upper(),
            college_email_verified=True,
        )

        response = self.client.post(
            reverse('api:bind-college-email-verify'),
            {'token': token},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.college_email_verified)

    def test_verified_college_email_database_constraint_is_case_insensitive(self):
        self.user.college_email = self.bind_college_email['college_email'].lower()
        self.user.college_email_verified = True
        self.user.save()
        second_user = create_user(
            username='second_user',
            email='second@example.com',
            is_active=True,
            college_email=self.bind_college_email['college_email'].upper(),
            college_email_verified=False,
        )

        second_user.save()
        second_user.college_email_verified = True
        with self.assertRaises(IntegrityError), transaction.atomic():
            second_user.save(update_fields=('college_email_verified',))
