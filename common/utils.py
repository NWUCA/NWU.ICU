from rest_framework.response import Response
from rest_framework import status


def return_response(message: str = None, errors=None, contents=None, status_code=status.HTTP_200_OK):
    if contents is None:
        contents = {}
    if errors is None:
        errors = {}
    if message is None:
        message = ""
    return Response({"message": message,
                     "errors": errors,
                     "contents": contents}, status=status_code)
