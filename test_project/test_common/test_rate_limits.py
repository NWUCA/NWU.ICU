import copy
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.test import APIClient, APIRequestFactory, APITestCase

from test_project.common import create_user
from utils.throttle import (
    InvalidCaptchaProof,
    _login_key,
    check_login_attempt,
    consume_captcha_proof,
    issue_captcha_proof,
    record_login_failure,
)


def rate_limit_settings(**updates):
    config = copy.deepcopy(settings.API_RATE_LIMITS)
    for name, values in updates.items():
        config[name].update(values)
    return override_settings(API_RATE_LIMITS=config)


class CaptchaProofTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()

    def tearDown(self):
        cache.clear()

    def request(self, browser='browser-one'):
        request = self.factory.post('/api/example/')
        request.user = AnonymousUser()
        request.nwu_browser_id = browser
        return request

    def test_proof_is_signed_scoped_bound_and_single_use(self):
        proof, ttl = issue_captcha_proof(self.request(), 'review_write')
        payload = signing.loads(proof, salt='nwuicu.captcha-proof.v1', max_age=ttl)
        self.assertEqual(payload['scope'], 'review_write')
        self.assertEqual(payload['actor'], 'browser:browser-one')
        self.assertIn('nonce', payload)
        self.assertIn('issued_at', payload)

        with self.assertRaises(InvalidCaptchaProof):
            consume_captcha_proof(self.request(), 'guestbook_write', proof)
        with self.assertRaises(InvalidCaptchaProof):
            consume_captcha_proof(self.request('browser-two'), 'review_write', proof)

        self.assertTrue(consume_captcha_proof(self.request(), 'review_write', proof))
        with self.assertRaises(InvalidCaptchaProof):
            consume_captcha_proof(self.request(), 'review_write', proof)

    def test_tampered_and_expired_proofs_are_rejected(self):
        request = self.request()
        with patch('django.core.signing.time.time', return_value=1_000):
            proof, _ = issue_captcha_proof(request, 'review_write')
        with self.assertRaises(InvalidCaptchaProof):
            consume_captcha_proof(request, 'review_write', proof + 'tampered')
        with patch('django.core.signing.time.time', return_value=1_121):
            with self.assertRaises(InvalidCaptchaProof):
                consume_captcha_proof(request, 'review_write', proof)

    def test_scope_must_be_server_allowlisted(self):
        with self.assertRaises(InvalidCaptchaProof):
            issue_captcha_proof(self.request(), 'made_up_scope')

    def test_login_backoff_increases_after_each_exhausted_captcha_grant(self):
        with rate_limit_settings(login={
            'captcha_after_failures': 0,
            'captcha_attempts': 1,
            'backoff_seconds': (30, 60, 120, 300),
        }):
            for expected_wait in (30, 60):
                proof, _ = issue_captcha_proof(self.request(), 'login')
                attempt = self.factory.post('/api/user/login/', HTTP_X_CAPTCHA_PROOF=proof)
                attempt.user = AnonymousUser()
                attempt.nwu_browser_id = 'browser-one'
                check_login_attempt(attempt, 'same-user')
                record_login_failure(attempt, 'same-user')

                with self.assertRaises(Throttled) as blocked:
                    check_login_attempt(self.request(), 'same-user')
                self.assertGreaterEqual(blocked.exception.wait, expected_wait - 1)
                cache.delete(_login_key('blocked', 'browser-one'))


class ContentRateLimitTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user(is_active=True)
        self.client.force_authenticate(self.user)
        self.review_url = reverse('api:review')

    def tearDown(self):
        cache.clear()

    def proof(self, scope):
        response = self.client.post(reverse('api:captcha'), {
            'captcha_key': 'test-key',
            'captcha_value': 'PASSED',
            'scope': scope,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.data['contents']['captcha_proof']

    def test_burst_requires_captcha_and_proof_allows_only_one_write(self):
        with rate_limit_settings(review_write={
            'burst': '2/minute', 'sustained': '10/day', 'captcha_on_burst': True,
        }):
            self.assertEqual(self.client.post(self.review_url, {}, format='json').status_code, 400)
            self.assertEqual(self.client.post(self.review_url, {}, format='json').status_code, 400)
            blocked = self.client.post(self.review_url, {}, format='json')
            self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(blocked.data['errors'][0]['err_code'], 'captcha_required')
            self.assertEqual(blocked.data['contents']['captcha_scope'], 'review_write')
            self.assertIn('Retry-After', blocked)

            proof = self.proof('review_write')
            allowed = self.client.post(
                self.review_url, {}, format='json', HTTP_X_CAPTCHA_PROOF=proof,
            )
            self.assertEqual(allowed.status_code, status.HTTP_400_BAD_REQUEST)
            reused = self.client.post(
                self.review_url, {}, format='json', HTTP_X_CAPTCHA_PROOF=proof,
            )
            self.assertEqual(reused.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(reused.data['errors'][0]['err_code'], 'invalid_captcha_proof')

    def test_daily_hard_limit_cannot_be_bypassed_by_proof(self):
        with rate_limit_settings(review_write={
            'burst': '1/minute', 'sustained': '2/day', 'captcha_on_burst': True,
        }):
            self.client.post(self.review_url, {}, format='json')
            first_proof = self.proof('review_write')
            self.client.post(self.review_url, {}, format='json', HTTP_X_CAPTCHA_PROOF=first_proof)
            second_proof = self.proof('review_write')
            blocked = self.client.post(
                self.review_url, {}, format='json', HTTP_X_CAPTCHA_PROOF=second_proof,
            )
            self.assertEqual(blocked.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
            self.assertEqual(blocked.data['errors'][0]['err_code'], 'too_many_requests')
            self.assertIn('Retry-After', blocked)

    def test_proof_cannot_cross_scope(self):
        with rate_limit_settings(review_write={
            'burst': '1/minute', 'sustained': '10/day', 'captcha_on_burst': True,
        }):
            self.client.post(self.review_url, {}, format='json')
            wrong_scope = self.proof('guestbook_write')
            response = self.client.post(
                self.review_url, {}, format='json', HTTP_X_CAPTCHA_PROOF=wrong_scope,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data['errors'][0]['err_code'], 'invalid_captcha_proof')

    def test_proof_cannot_cross_authenticated_users_on_the_same_ip(self):
        second_user = create_user(username='second_user', email='second@example.com', is_active=True)
        factory = APIRequestFactory()
        first_request = factory.post('/api/captcha/', REMOTE_ADDR='192.0.2.1')
        first_request.user = self.user
        first_request.nwu_browser_id = 'shared-browser'
        proof, _ = issue_captcha_proof(first_request, 'review_write')
        second_request = factory.post('/api/assessment/review/', REMOTE_ADDR='192.0.2.1')
        second_request.user = second_user
        second_request.nwu_browser_id = 'shared-browser'
        with self.assertRaises(InvalidCaptchaProof):
            consume_captcha_proof(second_request, 'review_write', proof)

    def test_users_on_the_same_campus_ip_have_independent_content_buckets(self):
        with rate_limit_settings(review_write={
            'burst': '1/minute', 'sustained': '10/day', 'captcha_on_burst': True,
        }):
            first = self.client.post(
                self.review_url, {}, format='json', REMOTE_ADDR='192.0.2.1',
            )
            blocked = self.client.post(
                self.review_url, {}, format='json', REMOTE_ADDR='192.0.2.1',
            )
            second_client = APIClient()
            second_client.force_authenticate(create_user(
                username='other_user', email='other@example.com', is_active=True,
            ))
            independent = second_client.post(
                self.review_url, {}, format='json', REMOTE_ADDR='192.0.2.1',
            )
        self.assertEqual(first.status_code, 400)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(independent.status_code, 400)

    def test_get_requests_do_not_consume_content_limits(self):
        with rate_limit_settings(review_write={'burst': '1/minute', 'sustained': '1/day'}):
            responses = [self.client.get(reverse('api:school')) for _ in range(20)]
        self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_guestbook_sixth_write_requires_captcha(self):
        with rate_limit_settings(guestbook_write={
            'burst': '5/minute', 'sustained': '30/day', 'captcha_on_burst': True,
        }):
            first_five = [
                self.client.post(reverse('api:guestbook'), {}, format='json')
                for _ in range(5)
            ]
            sixth = self.client.post(reverse('api:guestbook'), {}, format='json')
        self.assertTrue(all(response.status_code == 400 for response in first_five))
        self.assertEqual(sixth.status_code, 429)
        self.assertEqual(sixth.data['contents']['captcha_scope'], 'guestbook_write')

    def test_all_reply_entry_points_share_the_same_tenth_write_limit(self):
        with rate_limit_settings(reply_write={
            'burst': '10/minute', 'sustained': '100/day', 'captcha_on_burst': True,
        }):
            for _ in range(4):
                self.client.post(reverse('api:add_reply'), {}, format='json')
            for _ in range(3):
                self.client.post(reverse('api:guestbook-replies', args=[999]), {}, format='json')
            for _ in range(3):
                self.client.post(reverse('api:announcement-replies', args=[999]), {}, format='json')
            eleventh = self.client.post(reverse('api:add_reply'), {}, format='json')
        self.assertEqual(eleventh.status_code, 429)
        self.assertEqual(eleventh.data['contents']['captcha_scope'], 'reply_write')


class RegistrationRateLimitTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(CAPTCHA_TEST_MODE=False)
    @patch('user.views.enforce_email_delivery')
    @patch('user.views.enforce_policy')
    @patch('user.views.enforce_policies')
    def test_invalid_captcha_does_not_consume_target_or_success_quota(
        self, enforce_targets, enforce_success, enforce_email,
    ):
        response = self.client.post(reverse('api:register'), {
            'username': 'new_user',
            'password': 'Valid-password-123',
            'email': 'new@example.com',
            'captcha_key': 'missing-captcha',
            'captcha_value': 'wrong',
        }, format='json')
        self.assertEqual(response.status_code, 400)
        enforce_targets.assert_not_called()
        enforce_success.assert_not_called()
        enforce_email.assert_not_called()
