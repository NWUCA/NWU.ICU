from datetime import datetime

import pytest

from user.models import User


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


@pytest.fixture
def user(db):
    user = User.objects.create(
        username='test_user',
        name='test_name',
        cookie=b"",
        cookie_last_update=datetime.now(),
        nickname="nickname",
    )
    return user


@pytest.fixture
def user2(db):
    user = User.objects.create(
        username='test_user2',
        name='test_name2',
        cookie=b"",
        cookie_last_update=datetime.now(),
        nickname="nickname2",
    )
    return user


@pytest.fixture
def logged_in_client(user, client):
    client.force_login(user)
    return client
