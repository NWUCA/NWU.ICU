

from django.contrib.auth import get_user_model
from django.urls import reverse


def user_info():
    return {'username': 'test_user', 'email': 'test@example.com', 'password': 'test_password', 'nickname': "nickname"}


def create_user(**kwargs):
    data = user_info()
    data.update(kwargs)
    user = get_user_model().objects.create_user(
        **data,
    )
    return user


def login_user(client, user_info_dict=None):
    if user_info_dict is None:
        user_info_dict = user_info()
    client.login(username=user_info_dict['username'], password=user_info_dict['password'])
    return client


def check_login_status(client):
    response = client.get(reverse('api:profile'))
    return response.status_code == 200
