from user import views
from user.models import User


def test_login(monkeypatch, user, client):
    def mock_unified_login(username, raw_password, captcha, captcha_cookies):
        return views.LoginResult(True, '登陆成功', user.name, b"")

    monkeypatch.setattr(views, 'unified_login', mock_unified_login)

    # According to the doc:
    # https://docs.djangoproject.com/en/4.1/topics/testing/tools/#django.test.Client.session
    # To modify the session and then save it, it must be stored in a variable first
    # (because a new SessionStore is created every time this property is accessed)
    session = client.session
    session['captcha_cookies'] = {"foo": "bar"}
    session.save()
    r = client.post('/login/', data={'username': user.username, 'password': 'bar', 'captcha': 'foo'})
    print(r.content.decode())
    assert r.status_code == 302
    client.logout()  # session will be deleted when logged out

    session = client.session
    session['captcha_cookies'] = {"foo": "bar"}
    session.save()
    # login by a nonexistent user will create new user
    another = 'alice'
    r = client.post('/login/', data={'username': another, 'password': 'bar', 'captcha': 'foo'})
    print(User.objects.all())
    print(r.content.decode())
    assert r.status_code == 302
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
