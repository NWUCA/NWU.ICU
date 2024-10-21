import json
import random

from rest_framework import status
from rest_framework.exceptions import NotAuthenticated, Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler

from settings.settings import BASE_DIR
from utils import constants


def return_response(message: str = None, errors=None, contents=None, status_code=status.HTTP_200_OK):
    if contents is None:
        contents = {}
    if errors is None:
        errors = {}
    if message is None:
        message = ""
    errors_list = []
    for key, value in errors.items():
        errors_list.append({
            'field': key,
            'err_code': value['err_code'],
            'err_msg': value['err_msg']
        })
    return Response({"message": message,
                     "errors": errors_list,
                     "contents": contents}, status=status_code)


def get_err_msg(err_code: str):
    return {'err_code': err_code, 'err_msg': constants.errcode_dict[err_code]}


def get_msg_msg(msg_code: str):
    return constants.message_dict[msg_code]


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, NotAuthenticated):
        return return_response(errors={'login': get_err_msg('not_login')}, status_code=status.HTTP_401_UNAUTHORIZED)

    if isinstance(exc, Throttled):
        return return_response(errors={'throttle': get_err_msg('too_many_requests')},
                               status_code=status.HTTP_429_TOO_MANY_REQUESTS)
    return response


def generate_random_nickname():
    with open(BASE_DIR / 'utils' / 'static_file' / 'adjective.json', encoding='utf-8') as f:
        adjective = json.loads(f.read())
    with open(BASE_DIR / 'utils' / 'static_file' / 'noun.json', encoding='utf-8') as f:
        noun = json.loads(f.read())
    random_suffix = ''.join(
        random.choice(list('1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')) for _ in range(4))
    return adjective[random.randrange(len(adjective) - 1)] + '的' + noun[
        random.randrange(len(noun) - 1)] + random_suffix