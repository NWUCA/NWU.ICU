import json
import random

from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler

from course_assessment.models import Review
from settings import settings
from settings.settings import BASE_DIR
from utils import constants


def format_file_size(size):
    value = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            precision = 0 if unit == 'B' else 2
            return f'{value:.{precision}f} {unit}'
        value /= 1024


def return_response(message: str = None, errors=None, contents=None, status_code=status.HTTP_200_OK):
    if contents is None:
        contents = {}
    if errors is None:
        errors = {}
    if message is None:
        message = ""
    errors_list = []
    for key, value in errors.items():
        try:
            errors_list.append({
                'field': key,
                'err_code': value['err_code'],
                'err_msg': value['err_msg']
            })
        except TypeError:
            value = value[-1]
            errors_list.append({
                'field': key,
                'err_code': value.code,
                'err_msg': str(value)
            })
    return Response({"message": message,
                     "errors": errors_list,
                     "contents": contents}, status=status_code)


def get_err_msg(err_code: str):
    try:
        err_msg_dict = {'err_code': err_code, 'err_msg': constants.errcode_dict[err_code]}
    except KeyError:
        err_msg_dict = {'err_code': err_code, 'err_msg': err_code}
    return err_msg_dict


def get_msg_msg(msg_code: str):
    return constants.message_dict[msg_code]


def get_cache_key(cache_key: str):
    return constants.cache_key_dict[cache_key]


def get_user_avatar_info(user):
    """Return the additive public fields needed to render a user's avatar."""
    return {
        'uuid': user.uuid,
        'avatar': user.avatar_uuid,
        'has_avatar': str(user.avatar_uuid) != str(settings.DEFAULT_USER_AVATAR_UUID),
    }


def custom_exception_handler(exc, context):
    management_error_code = getattr(exc, 'err_code', None)
    if management_error_code:
        return return_response(
            errors={getattr(exc, 'field', 'auth'): {
                'err_code': management_error_code,
                'err_msg': getattr(exc, 'err_msg', str(exc)),
            }},
            status_code=exc.status_code,
        )
    response = exception_handler(exc, context)

    if isinstance(exc, NotAuthenticated):
        return return_response(errors={'login': get_err_msg('not_login')}, status_code=status.HTTP_401_UNAUTHORIZED)

    if isinstance(exc, Throttled):
        return return_response(errors={'throttle': get_err_msg('too_many_requests')},
                               status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return response


class userUtils:
    @staticmethod
    def get_user_info_in_review(review: Review):
        user_info = {
            "nickname": get_msg_msg(
                'anonymous_user_nickname') if review.anonymous else review.created_by.nickname,
            "id": -1 if review.anonymous else review.created_by.id,
            "avatar_uuid": settings.ANONYMOUS_USER_AVATAR_UUID if review.anonymous else review.created_by.avatar_uuid,
            'is_student': (
                not review.anonymous
                and review.created_by.college_email_verified
                and review.created_by.college_email is not None
                and review.created_by.college_email.endswith(
                    settings.UNIVERSITY_STUDENT_MAIL_SUFFIX)
            )
        }
        if not review.anonymous:
            user_info.update({
                'uuid': review.created_by.uuid,
                'has_avatar': str(review.created_by.avatar_uuid) != str(settings.DEFAULT_USER_AVATAR_UUID),
            })
        return user_info

    @staticmethod
    def generate_random_nickname():
        with open(BASE_DIR / 'utils' / 'static_file' / 'adjective.json', encoding='utf-8') as f:
            adjective = json.loads(f.read())
        with open(BASE_DIR / 'utils' / 'static_file' / 'noun.json', encoding='utf-8') as f:
            noun = json.loads(f.read())
        random_suffix = ''.join(
            random.choice(list('1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')) for _ in range(4))
        return adjective[random.randrange(len(adjective) - 1)] + '的' + noun[
            random.randrange(len(noun) - 1)] + random_suffix
