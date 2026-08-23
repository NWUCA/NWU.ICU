from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from common.messaging import get_unread_message_count, mark_conversation_read, send_direct_message
from common.models import Conversation, ConversationParticipant, DirectMessage, Notification
from test_project.common import create_user


@override_settings(DEBUG=True)
class MessageTests(APITestCase):
    def setUp(self):
        self.user_a = create_user(username='message_user_a', email='a@example.com')
        self.user_b = create_user(username='message_user_b', email='b@example.com')
        self.user_c = create_user(username='message_user_c', email='c@example.com')
        self.client_a = APIClient()
        self.client_b = APIClient()
        self.client_c = APIClient()
        self.client_a.force_login(self.user_a)
        self.client_b.force_login(self.user_b)
        self.client_c.force_login(self.user_c)

    def detail_url(self, peer):
        return reverse('api:check_particular_message', kwargs={
            'classify': 'user',
            'chatter_id': peer.id,
        })

    def test_opening_conversation_marks_snapshot_but_not_later_messages_read(self):
        for index in range(15):
            response = self.client_a.post(reverse('api:send_message'), {
                'receiver': self.user_b.id,
                'content': f'message-{index}',
            }, format='json')
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        unread = self.client_b.get(reverse('api:unread_message')).data['contents']
        self.assertEqual(unread['unread']['user'], 15)

        detail = self.client_b.get(self.detail_url(self.user_a))
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        body = detail.data['contents']
        self.assertEqual([item['content'] for item in body['results']], [
            f'message-{index}' for index in range(5, 15)
        ])
        self.assertEqual(
            self.client_b.get(reverse('api:unread_message')).data['contents']['unread']['user'],
            15,
        )

        read_response = self.client_b.post(
            reverse('api:read_conversation', kwargs={'chatter_id': self.user_a.id}),
            {'through_message_id': body['snapshot_latest_message_id']},
            format='json',
        )
        self.assertEqual(read_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client_b.get(reverse('api:unread_message')).data['contents']['unread']['user'],
            0,
        )

        later = send_direct_message(self.user_a, self.user_b, 'arrived-after-snapshot')
        self.client_b.post(
            reverse('api:read_conversation', kwargs={'chatter_id': self.user_a.id}),
            {'through_message_id': body['snapshot_latest_message_id']},
            format='json',
        )
        conversation = Conversation.objects.get(user_low_id=self.user_a.id, user_high_id=self.user_b.id)
        self.assertEqual(get_unread_message_count(conversation, self.user_b), 1)
        self.assertGreater(later.id, body['snapshot_latest_message_id'])

    def test_after_cursor_drains_burst_without_gaps_or_duplicates(self):
        first = send_direct_message(self.user_a, self.user_b, 'first')
        expected = [send_direct_message(self.user_a, self.user_b, f'burst-{index}').id for index in range(25)]

        cursor = first.id
        received = []
        while True:
            response = self.client_b.get(self.detail_url(self.user_a), {
                'after_id': cursor,
                'page_size': 10,
            })
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            contents = response.data['contents']
            page_ids = [item['id'] for item in contents['results']]
            received.extend(page_ids)
            if page_ids:
                cursor = page_ids[-1]
            if not contents['has_more']:
                break

        self.assertEqual(received, expected)
        self.assertEqual(len(received), len(set(received)))

    def test_object_permissions_and_message_length(self):
        send_direct_message(self.user_a, self.user_b, 'private')
        self.assertEqual(self.client_c.get(self.detail_url(self.user_a)).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            self.client_c.post(
                reverse('api:read_conversation', kwargs={'chatter_id': self.user_a.id}),
                {'through_message_id': 1},
                format='json',
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        too_long = self.client_a.post(reverse('api:send_message'), {
            'receiver': self.user_b.id,
            'content': 'x' * 501,
        }, format='json')
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)

    def test_notification_get_is_read_only_and_batch_read_is_owner_scoped(self):
        notice = Notification.objects.create(
            recipient=self.user_b,
            kind=Notification.KIND_SYSTEM,
            dedupe_key='test-system-notice',
            payload={'title': 'System', 'content': 'Only B can read this'},
        )
        response = self.client_b.get(reverse('api:check_all_message', args=['system']))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)

        foreign_read = self.client_c.post(
            reverse('api:read_notifications'), {'ids': [notice.id]}, format='json'
        )
        self.assertEqual(foreign_read.data['contents']['updated'], 0)
        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)

        own_read = self.client_b.post(
            reverse('api:read_notifications'), {'ids': [notice.id]}, format='json'
        )
        self.assertEqual(own_read.data['contents']['updated'], 1)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.read_at)


class MessageConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user_a = create_user(username='concurrent_a', email='concurrent_a@example.com')
        self.user_b = create_user(username='concurrent_b', email='concurrent_b@example.com')

    @staticmethod
    def _send(sender_id, recipient_id, content):
        close_old_connections()
        from user.models import User
        sender = User.objects.get(pk=sender_id)
        recipient = User.objects.get(pk=recipient_id)
        message = send_direct_message(sender, recipient, content)
        close_old_connections()
        return message.id

    def test_concurrent_first_messages_create_one_conversation_and_monotonic_preview(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(
                lambda content: self._send(self.user_a.id, self.user_b.id, content),
                ('one', 'two'),
            ))
        self.assertEqual(Conversation.objects.count(), 1)
        conversation = Conversation.objects.get()
        self.assertEqual(DirectMessage.objects.filter(conversation=conversation).count(), 2)
        self.assertEqual(conversation.last_message_id, max(ids))
        self.assertEqual(
            set(ConversationParticipant.objects.filter(conversation=conversation).values_list('user_id', flat=True)),
            {self.user_a.id, self.user_b.id},
        )

    def test_read_watermark_does_not_consume_concurrent_later_message(self):
        first = send_direct_message(self.user_a, self.user_b, 'snapshot')
        conversation = first.conversation
        with ThreadPoolExecutor(max_workers=2) as executor:
            send_future = executor.submit(self._send, self.user_a.id, self.user_b.id, 'later')
            read_future = executor.submit(
                mark_conversation_read,
                conversation,
                self.user_b,
                first.id,
            )
            send_future.result()
            read_future.result()
        conversation.refresh_from_db()
        self.assertEqual(get_unread_message_count(conversation, self.user_b), 1)
