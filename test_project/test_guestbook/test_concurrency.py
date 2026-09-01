from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from common.models import Notification
from guestbook.models import GuestbookEntry
from test_project.common import create_user


class GuestbookConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.author = create_user(username='concurrent-author', email='concurrent-author@example.com')
        self.reader = create_user(username='concurrent-reader', email='concurrent-reader@example.com')

    def run_concurrently(self, *actions):
        barrier = Barrier(len(actions))

        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            futures = [executor.submit(run, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def request(self, user, method, url, data=None):
        client = APIClient()
        client.force_authenticate(user)
        return getattr(client, method)(url, data, format='json')

    def test_concurrent_duplicate_posts_create_one_entry(self):
        data = {'content': '<p>publish once</p>', 'submission_id': str(uuid4())}
        responses = self.run_concurrently(*[
            lambda: self.request(self.author, 'post', reverse('api:guestbook'), data) for _ in range(2)
        ])
        self.assertEqual([response.status_code for response in responses], [201, 201])
        self.assertEqual(GuestbookEntry.objects.count(), 1)
        self.assertEqual(responses[0].data['contents']['entry']['id'], responses[1].data['contents']['entry']['id'])

    def test_deletion_serializes_with_likes_and_replies(self):
        root = GuestbookEntry.objects.create(author=self.author, content='<p>original</p>')
        responses = self.run_concurrently(
            lambda: self.request(self.author, 'delete', reverse('api:guestbook-detail', kwargs={'entry_id': root.id})),
            lambda: self.request(self.reader, 'put', reverse('api:guestbook-like', kwargs={'entry_id': root.id}), {'liked': True}),
            lambda: self.request(self.reader, 'post', reverse('api:guestbook-replies', kwargs={'entry_id': root.id}), {'content': 'reply', 'submission_id': str(uuid4())}),
        )
        self.assertEqual(responses[0].status_code, 200)
        self.assertIn(responses[1].status_code, (200, 400))
        self.assertIn(responses[2].status_code, (201, 400))
        root.refresh_from_db()
        self.assertTrue(root.is_deleted)
        self.assertEqual(root.content, '<p>original</p>')
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())
