from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from test_project.common import create_user
from user import tokens
from user.tokens import (
    UserTokenPurpose,
    consume_user_token,
    get_user_token_data,
    issue_user_token,
)


class UserTokenLifecycleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = create_user(is_active=True)

    def tearDown(self):
        cache.clear()

    def test_only_latest_token_remains_valid_for_each_purpose(self):
        for purpose in UserTokenPurpose:
            with self.subTest(purpose=purpose):
                generator = tokens._TOKEN_GENERATORS[purpose]
                with patch.object(
                    generator,
                    'make_token',
                    side_effect=[f'{purpose.value}-old', f'{purpose.value}-new'],
                ):
                    old_token = issue_user_token(self.user, purpose, marker='old')
                    new_token = issue_user_token(self.user, purpose, marker='new')

                self.assertIsNone(get_user_token_data(old_token, purpose))
                self.assertEqual(
                    get_user_token_data(new_token, purpose)['marker'], 'new'
                )

    def test_consuming_stale_token_does_not_invalidate_latest_token(self):
        purpose = UserTokenPurpose.PASSWORD_RESET
        generator = tokens._TOKEN_GENERATORS[purpose]
        with patch.object(generator, 'make_token', side_effect=['old-token', 'new-token']):
            old_token = issue_user_token(self.user, purpose)
            new_token = issue_user_token(self.user, purpose)

        consume_user_token(self.user, old_token, purpose)

        self.assertIsNotNone(get_user_token_data(new_token, purpose))

    def test_missing_token_is_rejected(self):
        self.assertIsNone(
            get_user_token_data('', UserTokenPurpose.ACCOUNT_ACTIVATION)
        )
