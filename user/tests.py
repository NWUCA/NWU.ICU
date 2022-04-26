from user import views
from user.models import User


def test_login(monkeypatch, user, client):
    def mock_unified_login(username, raw_password):
        return views.LoginResult(True, '登陆成功', user.name, b"")

    monkeypatch.setattr(views, 'unified_login', mock_unified_login)

    r = client.post('/login/', data={'username': user.username, 'password': 'bar'})
    assert r.status_code == 302
    client.logout()

    # login by a nonexistent user will create new user
    another = 'alice'
    r = client.post('/login/', data={'username': another, 'password': 'bar'})
    print(User.objects.all())
    assert User.objects.get(username=another)
    client.logout()

    # test malformed login
    r = client.post('/login/', data={'username': user.username})
    assert "登陆表单异常" in r.content.decode()


def test_need_to_set_nickname(user, logged_in_client):
    user.nickname = ""
    user.save()
    r = logged_in_client.get('/', follow=True)
    assert r.redirect_chain[0][0].endswith('/settings/')

    r = logged_in_client.post('/settings/', data={"nickname": "alice"})
    assert r.status_code == 302
    r = logged_in_client.get('/')
    assert r.status_code == 200
