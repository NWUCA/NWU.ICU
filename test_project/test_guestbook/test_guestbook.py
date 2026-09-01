from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from guestbook.models import GuestbookEntry, GuestbookLike, GuestbookReport
from test_project.common import create_user


class GuestbookApiTests(APITestCase):
    def setUp(self):
        self.author = create_user(username='guestbook-author', email='guestbook-author@example.com')
        self.reader = create_user(username='guestbook-reader', email='guestbook-reader@example.com')
        self.author_client = APIClient()
        self.author_client.force_login(self.author)
        self.reader_client = APIClient()
        self.reader_client.force_login(self.reader)

    def entry_url(self, entry):
        return reverse('api:guestbook-detail', kwargs={'entry_id': entry.id})

    def replies_url(self, entry):
        return reverse('api:guestbook-replies', kwargs={'entry_id': entry.id})

    def test_public_list_and_authenticated_post(self):
        public_client = APIClient()
        self.assertEqual(public_client.get(reverse('api:guestbook')).status_code, status.HTTP_200_OK)
        self.assertEqual(
            public_client.post(reverse('api:guestbook'), {'content': '<p>hello</p>'}, format='json').status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        response = self.author_client.post(reverse('api:guestbook'), {
            'content': '<p><strong>hello</strong><script>discarded</script></p>',
            'anonymous': False,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = response.data['contents']['entry']
        self.assertEqual(entry['content'], '<p><strong>hello</strong></p>')
        self.assertEqual(entry['author']['nickname'], self.author.nickname)
        self.assertTrue(entry['is_me'])

    def test_anonymous_entry_never_exposes_author_identity(self):
        entry = GuestbookEntry.objects.create(author=self.author, content='<p>secret</p>', anonymous=True)
        response = self.reader_client.get(self.entry_url(entry))
        author = response.data['contents']['entry']['author']
        self.assertEqual(author['nickname'], '匿名用户')
        self.assertIsNone(author['id'])
        self.assertEqual(author['avatar'], str(settings.ANONYMOUS_USER_AVATAR_UUID))

    def test_reply_tree_context_and_soft_deletion(self):
        root = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        first = self.reader_client.post(self.replies_url(root), {'content': '<p>first</p>'}, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        first_entry = GuestbookEntry.objects.get(id=first.data['contents']['entry']['id'])
        second = self.author_client.post(self.replies_url(first_entry), {'content': '<p>second</p>'}, format='json')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        second_entry = GuestbookEntry.objects.get(id=second.data['contents']['entry']['id'])
        self.assertEqual(first_entry.root_id, root.id)
        self.assertEqual(second_entry.root_id, root.id)

        context = self.reader_client.get(reverse('api:guestbook-context', kwargs={'entry_id': second_entry.id}))
        self.assertEqual(context.data['contents']['path'], [root.id, first_entry.id, second_entry.id])

        self.assertEqual(self.reader_client.delete(self.entry_url(first_entry)).status_code, status.HTTP_200_OK)
        delete = self.reader_client.delete(self.entry_url(first_entry))
        self.assertEqual(delete.status_code, status.HTTP_200_OK)
        visible = self.author_client.get(self.replies_url(root)).data['contents']['results'][0]
        self.assertTrue(visible['is_deleted'])
        self.assertEqual(visible['content'], '[内容已删除]')
        self.assertEqual(GuestbookEntry.all_objects.filter(id=second_entry.id).count(), 1)
        self.assertEqual(
            self.author_client.post(self.replies_url(first_entry), {'content': '<p>blocked</p>'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_like_and_report_are_idempotent(self):
        entry = GuestbookEntry.objects.create(author=self.author, content='<p>like me</p>')
        like_url = reverse('api:guestbook-like', kwargs={'entry_id': entry.id})
        self.assertEqual(self.reader_client.put(like_url, {'liked': True}, format='json').status_code, status.HTTP_200_OK)
        self.assertEqual(self.reader_client.put(like_url, {'liked': True}, format='json').status_code, status.HTTP_200_OK)
        entry.refresh_from_db()
        self.assertEqual(entry.like_count, 1)
        self.assertEqual(GuestbookLike.objects.count(), 1)
        self.reader_client.put(like_url, {'liked': False}, format='json')
        entry.refresh_from_db()
        self.assertEqual(entry.like_count, 0)

        report_url = reverse('api:guestbook-report', kwargs={'entry_id': entry.id})
        created = self.reader_client.post(report_url, {'reason': 'spam', 'detail': '广告'}, format='json')
        duplicate = self.reader_client.post(report_url, {'reason': 'spam'}, format='json')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate.status_code, status.HTTP_200_OK)
        self.assertEqual(GuestbookReport.objects.count(), 1)

    def test_content_limit_is_counted_as_plain_text(self):
        too_long = self.author_client.post(reverse('api:guestbook'), {
            'content': f'<p>{"字" * 501}</p>',
        }, format='json')
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)
