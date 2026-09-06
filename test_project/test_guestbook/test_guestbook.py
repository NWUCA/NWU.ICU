from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from guestbook.models import GuestbookEntry, GuestbookLike, GuestbookReport
from common.models import Notification
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

    def test_announcements_share_entries_but_are_isolated_and_admin_only_to_create(self):
        admin = create_user(username='announcement-admin', email='announcement-admin@example.com')
        admin.is_staff = True
        admin.save(update_fields=('is_staff',))
        admin_client = APIClient()
        admin_client.force_login(admin)
        announcements_url = reverse('api:announcements')

        self.assertEqual(
            self.author_client.post(announcements_url, {'content': '<p>blocked</p>'}, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        created = admin_client.post(
            announcements_url, {'title': 'Important notice', 'content': '<p>notice</p>', 'anonymous': True}, format='json'
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        announcement = GuestbookEntry.objects.get(pk=created.data['contents']['entry']['id'])
        self.assertEqual(announcement.board, GuestbookEntry.BOARD_ANNOUNCEMENT)
        self.assertEqual(created.data['contents']['entry']['title'], 'Important notice')
        self.assertFalse(announcement.anonymous)
        self.assertEqual(
            admin_client.post(announcements_url, {'content': '<p>missing title</p>'}, format='json').status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(self.author_client.get(announcements_url).data['contents']['count'], 1)
        self.assertEqual(self.author_client.get(reverse('api:guestbook')).data['contents']['count'], 0)

        reply_url = reverse('api:announcement-replies', kwargs={'entry_id': announcement.id})
        reply = self.author_client.post(reply_url, {'content': '<p>reply</p>'}, format='json')
        self.assertEqual(reply.status_code, status.HTTP_201_CREATED)
        reply_entry = GuestbookEntry.objects.get(pk=reply.data['contents']['entry']['id'])
        self.assertEqual(reply_entry.board, GuestbookEntry.BOARD_ANNOUNCEMENT)
        like_url = reverse('api:announcement-like', kwargs={'entry_id': announcement.id})
        self.assertEqual(
            self.author_client.put(like_url, {'liked': True}, format='json').status_code,
            status.HTTP_200_OK,
        )
        announcement.refresh_from_db()
        self.assertEqual(announcement.like_count, 1)
        self.assertEqual(
            self.author_client.post(
                reverse('api:announcement-report', kwargs={'entry_id': announcement.id}),
                {'reason': 'spam'}, format='json',
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.reader_client.post(
                reverse('api:announcement-report', kwargs={'entry_id': reply_entry.id}),
                {'reason': 'abuse'}, format='json',
            ).status_code,
            status.HTTP_201_CREATED,
        )

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

    def test_reply_and_like_create_guestbook_notifications_without_content_snapshots(self):
        entry = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        reply = self.reader_client.post(self.replies_url(entry), {'content': '<p>reply</p>'}, format='json')
        self.assertEqual(reply.status_code, status.HTTP_201_CREATED)
        reply_notice = Notification.objects.get(recipient=self.author, kind=Notification.KIND_REPLY)
        self.assertEqual(reply_notice.payload['source'], 'guestbook')
        self.assertNotIn('content', reply_notice.payload['guestbook'])
        self.assertNotIn('content', reply_notice.payload['reply'])
        self.assertIsInstance(reply_notice.payload['created_by']['has_avatar'], bool)

        like_url = reverse('api:guestbook-like', kwargs={'entry_id': entry.id})
        self.reader_client.put(like_url, {'liked': True}, format='json')
        like_notice = Notification.objects.get(recipient=self.author, kind=Notification.KIND_LIKE)
        self.assertEqual(like_notice.payload['guestbook']['root_id'], entry.id)
        self.assertNotIn('content', like_notice.payload['guestbook'])

    def test_content_limit_is_counted_as_plain_text(self):
        too_long = self.author_client.post(reverse('api:guestbook'), {
            'content': f'<p>{"字" * 501}</p>',
        }, format='json')
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deletion_preserves_tree_and_removes_related_notifications(self):
        root = GuestbookEntry.objects.create(author=self.author, content='<p>original</p>')
        response = self.reader_client.post(self.replies_url(root), {'content': '<p>reply</p>'}, format='json')
        child = GuestbookEntry.objects.get(pk=response.data['contents']['entry']['id'])
        self.reader_client.put(reverse('api:guestbook-like', kwargs={'entry_id': root.id}), {'liked': True}, format='json')
        self.assertEqual(Notification.objects.filter(recipient=self.author).count(), 2)
        self.author_client.delete(self.entry_url(root))
        root.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(root.is_deleted)
        self.assertEqual(root.content, '<p>original</p>')
        self.assertEqual(child.parent_id, root.id)
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())
        from guestbook.notifications import notify_guestbook_like, notify_guestbook_reply
        notify_guestbook_like(root)
        child.parent = root
        notify_guestbook_reply(child)
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())

    def test_deleted_reply_is_removed_from_notifications(self):
        root = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        response = self.reader_client.post(self.replies_url(root), {'content': '<p>reply</p>'}, format='json')
        child = GuestbookEntry.objects.get(pk=response.data['contents']['entry']['id'])
        self.assertTrue(Notification.objects.filter(recipient=self.author).exists())
        self.reader_client.delete(self.entry_url(child))
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())

    def test_admin_deletion_is_soft_and_content_is_read_only(self):
        from django.contrib.admin.sites import AdminSite
        from guestbook.admin import GuestbookEntryAdmin
        root = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        child = GuestbookEntry.objects.create(author=self.reader, content='<p>reply</p>', parent=root, root=root)
        admin = GuestbookEntryAdmin(GuestbookEntry, AdminSite())
        admin.delete_queryset(None, GuestbookEntry.all_objects.filter(pk=root.pk))
        root.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(root.is_deleted)
        self.assertEqual(root.content, '<p>root</p>')
        self.assertEqual(child.parent_id, root.id)
        self.assertIn('content', admin.readonly_fields)
        self.assertIn('parent', admin.readonly_fields)

    def test_repeated_and_removed_likes_do_not_reset_read_state(self):
        from django.utils import timezone
        root = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        url = reverse('api:guestbook-like', kwargs={'entry_id': root.id})
        self.reader_client.put(url, {'liked': True}, format='json')
        notice = Notification.objects.get(recipient=self.author, kind=Notification.KIND_LIKE)
        read_at = timezone.now()
        notice.read_at = read_at
        notice.save()
        self.reader_client.put(url, {'liked': True}, format='json')
        self.author_client.put(url, {'liked': True}, format='json')
        notice.refresh_from_db()
        self.assertEqual(notice.read_at, read_at)
        other = create_user(username='guestbook-other', email='guestbook-other@example.com')
        other_client = APIClient()
        other_client.force_login(other)
        other_client.put(url, {'liked': True}, format='json')
        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)
        notice.read_at = read_at
        notice.save()
        self.reader_client.put(url, {'liked': False}, format='json')
        notice.refresh_from_db()
        self.assertEqual(notice.read_at, read_at)
        self.assertEqual(notice.payload['like']['like'], 2)

    def test_notification_text_resolves_current_entry_instead_of_legacy_snapshot(self):
        from guestbook.notifications import hydrate_guestbook_notifications
        root = GuestbookEntry.objects.create(author=self.author, content='<p>root</p>')
        response = self.reader_client.post(self.replies_url(root), {'content': '<p>current</p>'}, format='json')
        notice = Notification.objects.get(recipient=self.author, kind=Notification.KIND_REPLY)
        notice.payload['reply']['content'] = 'stale snapshot'
        hydrate_guestbook_notifications([notice])
        self.assertEqual(notice.payload['reply']['content'], '<p>current</p>')
        GuestbookEntry.all_objects.filter(pk=response.data['contents']['entry']['id']).update(is_deleted=True)
        hydrate_guestbook_notifications([notice])
        self.assertEqual(notice.payload['reply']['content'], '[内容已删除]')

    def test_retrying_submission_returns_original_without_duplicate_notification(self):
        from uuid import uuid4
        data = {'content': '<p>post</p>', 'submission_id': str(uuid4())}
        root_response = self.author_client.post(reverse('api:guestbook'), data, format='json')
        retry = self.author_client.post(reverse('api:guestbook'), data, format='json')
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(retry.data['contents']['entry']['id'], root_response.data['contents']['entry']['id'])
        root = GuestbookEntry.objects.get(pk=root_response.data['contents']['entry']['id'])
        reply_data = {'content': '<p>reply</p>', 'submission_id': str(uuid4())}
        first = self.reader_client.post(self.replies_url(root), reply_data, format='json')
        second = self.reader_client.post(self.replies_url(root), reply_data, format='json')
        self.assertEqual(first.data['contents']['entry']['id'], second.data['contents']['entry']['id'])
        self.assertEqual(Notification.objects.filter(recipient=self.author).count(), 1)
        conflict = self.reader_client.post(self.replies_url(root), {**reply_data, 'content': 'changed'}, format='json')
        self.assertEqual(conflict.status_code, 409)
        root.soft_delete()
        self.assertEqual(self.reader_client.post(self.replies_url(root), reply_data, format='json').status_code, 201)
        self.assertFalse(Notification.objects.filter(recipient=self.author).exists())

    def test_nested_unsafe_tags_are_discarded_without_server_error(self):
        response = self.author_client.post(reverse('api:guestbook'), {
            'content': '<p>safe</p><object><div><p>unsafe</p></div></object>',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['contents']['entry']['content'], '<p>safe</p>')

    def test_context_includes_target_beyond_first_page_and_counts_direct_children(self):
        root = GuestbookEntry.objects.create(author=self.author, content='root')
        for _ in range(11):
            child = GuestbookEntry.objects.create(author=self.reader, content='child', parent=root, root=root)
        leaf = GuestbookEntry.objects.create(author=self.author, content='leaf', parent=child, root=root)
        response = APIClient().get(reverse('api:guestbook-context', kwargs={'entry_id': leaf.id}))
        entries = response.data['contents']['entries']
        self.assertEqual([entry['id'] for entry in entries], [root.id, child.id, leaf.id])
        self.assertEqual(entries[0]['reply_count'], 12)
        self.assertEqual(entries[0]['children_count'], 11)
        self.assertEqual(entries[1]['children_count'], 1)
        self.assertEqual(entries[2]['reply_count'], 0)
        self.assertEqual(entries[2]['children_count'], 0)
