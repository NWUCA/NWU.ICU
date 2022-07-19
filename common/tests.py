from django.contrib.messages import get_messages as _get_messages


def get_messages(request):
    messages = [m.message for m in _get_messages(request)]
    return messages


def test_change_nickname(logged_in_client, user, user2):
    r = logged_in_client.post('/settings/', data={'nickname': 'foo'})
    assert get_messages(r.wsgi_request)[0] == '修改成功'

    r = logged_in_client.post('/settings/', data={'nickname': user2.nickname})
    print(get_messages(r.wsgi_request))
    # FIXME: why messages are not cleaned after used?
    assert get_messages(r.wsgi_request)[-1] == '昵称已被使用'

    r = logged_in_client.post('/settings/', data={'nickname': "Foo" * 30})
    assert get_messages(r.wsgi_request)[-1] == '昵称不合法'
