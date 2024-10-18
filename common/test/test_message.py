from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from common.models import Chat


@override_settings(DEBUG=True)
class MessageTests(APITestCase):
    def setUp(self):
        self.register_userA_data = {
            "username": "testUserA",
            "password": "testPassword1",
            "email": "userA@exapmple.com",
            "captcha_key": "test_captcha",
            "captcha_value": "PASSED"
        }
        self.register_userB_data = {
            "username": "testUserB",
            "password": "testPassword1",
            "email": "userB@exapmple.com",
            "captcha_key": "test_captcha",
            "captcha_value": "PASSED"
        }
        self.register_url = reverse('api:register')
        self.login_url = reverse('api:login')
        self.active_url = reverse('api:register')
        self.send_message_url = reverse('api:send_message')
        self.user_profile_url = reverse('api:profile')
        self.unread_count_url = reverse('api:unread_message')
        self.client_A = APIClient()
        self.client_B = APIClient()
        token_A = self.client_A.post(self.register_url, self.register_userA_data, format='json').data['contents'][
            'token']
        token_B = self.client_B.post(self.register_url, self.register_userB_data, format='json').data['contents'][
            'token']
        self.client_A.get(self.active_url + "?token=" + token_A)
        self.client_B.get(self.active_url + "?token=" + token_B)
        self.client_A.post(self.login_url, self.register_userA_data, format='json')
        self.client_B.post(self.login_url, self.register_userB_data, format='json')
        self.user_A_id = self.client_A.get(self.user_profile_url).data['contents']['id']
        self.user_B_id = self.client_B.get(self.user_profile_url).data['contents']['id']

    def test_send_message(self):
        data_A = {
            "receiver": self.user_B_id,
            "content": "Hello, testUserB"
        }
        response = None
        for i in range(15):  # user_a 发送15条消息给user_b
            data_A['content'] = f'Hello, testUserB{i}'
            response = self.client_A.post(self.send_message_url, data_A, format='json')
        chat = Chat.objects.get(sender=self.user_A_id, receiver=self.user_B_id)
        A_unread_count = self.client_B.get(self.unread_count_url).data['contents']
        self.assertEqual(chat.classify, 'user')
        self.assertEqual(chat.receiver_unread_count, 15)
        self.assertEqual(A_unread_count['unread']['user'], 15)
        self.assertEqual(chat.sender_unread_count, 0)
        self.assertEqual(chat.last_message_content, 'Hello, testUserB14')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user_A_to_user_B_message = self.client_A.get(reverse('api:check_particular_message',
                                                             kwargs={'classify': 'user',
                                                                     'chatter_id': self.user_A_id}),
                                                     format='json').data['contents']  # A读了10条
        self.assertEqual(len(user_A_to_user_B_message['chats']), 10)
        self.assertEqual(user_A_to_user_B_message['chats'][-1]['content'], 'Hello, testUserB5')  # 默认分页大小为10

        data_B = {
            "receiver": self.user_A_id,
            "content": "Hello, testUserA"
        }
        for i in range(10):  # user_b 发送10条消息给user_a
            data_B['content'] = f'Hello, testUserA{i}'
            response = self.client_B.post(self.send_message_url, data_B, format='json')
        B_unread_count = self.client_B.get(self.unread_count_url).data['contents']['total']
        chat.refresh_from_db()
        self.assertEqual(chat.sender_unread_count, 10)
        self.assertEqual(chat.receiver_unread_count, 15)  # 上面读了10条, 一共发了15条, 所以还有5条未读
        self.assertEqual(B_unread_count, 15)
    # def test_like_notice(self):
