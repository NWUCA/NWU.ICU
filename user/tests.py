from user import views
from user.models import User


def test_login(monkeypatch, user, client):
    def mock_unified_login(username, raw_password):
        return views.LoginResult(True, '登陆成功', user.name, b"")

    monkeypatch.setattr(views, 'unified_login', mock_unified_login)

    r = client.post('/login/', data={'username': 'foo', 'password': 'bar'})
    assert r.status_code == 302

    # login by a nonexistent user will create new user
    another = 'alice'
    r = client.post('/login/', data={'username': another, 'password': 'bar'})
    assert User.objects.get(username=another)
