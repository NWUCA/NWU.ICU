from rest_framework import status
from rest_framework.exceptions import NotAuthenticated
from rest_framework.response import Response
from rest_framework.views import exception_handler

from common import constants


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


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if isinstance(exc, NotAuthenticated):
        return return_response(errors={'login': get_err_msg('not_login')}, status_code=status.HTTP_401_UNAUTHORIZED)

    return response
