from enum import Enum

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.cache import cache


class UserTokenPurpose(str, Enum):
    ACCOUNT_ACTIVATION = 'account_activation'
    PASSWORD_RESET = 'password_reset'
    COLLEGE_EMAIL_BIND = 'college_email_bind'


class AccountActivationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'nwuicu.user.tokens.account_activation'

    def _make_hash_value(self, user, timestamp):
        return f'{super()._make_hash_value(user, timestamp)}{user.is_active}'


class PasswordResetPurposeTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'nwuicu.user.tokens.password_reset'


class CollegeEmailBindTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'nwuicu.user.tokens.college_email_bind'

    def _make_hash_value(self, user, timestamp):
        return (
            f'{user.pk}{timestamp}{user.college_email}'
            f'{user.college_email_verified}'
        )


_TOKEN_GENERATORS = {
    UserTokenPurpose.ACCOUNT_ACTIVATION: AccountActivationTokenGenerator(),
    UserTokenPurpose.PASSWORD_RESET: PasswordResetPurposeTokenGenerator(),
    UserTokenPurpose.COLLEGE_EMAIL_BIND: CollegeEmailBindTokenGenerator(),
}


def _token_cache_key(purpose: UserTokenPurpose, token: str) -> str:
    return f'user-token:{purpose.value}:token:{token}'


def _user_cache_key(purpose: UserTokenPurpose, user_id: int) -> str:
    return f'user-token:{purpose.value}:user:{user_id}'


def issue_user_token(user, purpose: UserTokenPurpose, **extra_data) -> str:
    """Issue the only currently valid token for a user and a specific purpose."""
    user_key = _user_cache_key(purpose, user.pk)
    previous_token = cache.get(user_key)
    if previous_token:
        cache.delete(_token_cache_key(purpose, previous_token))

    token = _TOKEN_GENERATORS[purpose].make_token(user)
    token_data = {
        'purpose': purpose.value,
        'user_id': user.pk,
        **extra_data,
    }
    timeout = getattr(settings, 'USER_ACTION_TOKEN_TIMEOUT', 24 * 60 * 60)
    cache.set_many(
        {
            _token_cache_key(purpose, token): token_data,
            user_key: token,
        },
        timeout=timeout,
    )
    return token


def get_user_token_data(token: str, purpose: UserTokenPurpose):
    if not token:
        return None

    token_data = cache.get(_token_cache_key(purpose, token))
    if not isinstance(token_data, dict):
        return None
    if token_data.get('purpose') != purpose.value:
        return None

    user_id = token_data.get('user_id')
    if not user_id:
        return None
    if cache.get(_user_cache_key(purpose, user_id)) != token:
        return None

    return token_data


def check_user_token(user, token: str, purpose: UserTokenPurpose) -> bool:
    return _TOKEN_GENERATORS[purpose].check_token(user, token)


def consume_user_token(user, token: str, purpose: UserTokenPurpose) -> None:
    cache.delete(_token_cache_key(purpose, token))
    user_key = _user_cache_key(purpose, user.pk)
    if cache.get(user_key) == token:
        cache.delete(user_key)
