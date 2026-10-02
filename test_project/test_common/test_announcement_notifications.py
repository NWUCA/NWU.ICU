from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from common.admin import BulletinsAdmin
from common.announcement_notifications import (
    hydrate_announcement_notifications,
    notify_bulletin_published,
)
from common.models import Bulletin, Notification
from guestbook.announcements import (
    delete_announcement,
    publish_announcement,
    set_announcement_visibility,
    update_announcement,
)
from guestbook.models import GuestbookEntry
from test_project.common import create_user


class AnnouncementSystemNotificationTests(APITestCase):
    def setUp(self):
        self.author = create_user(
            username='announcement-author', email='author@example.com', is_staff=True
        )
        self.reader = create_user(username='announcement-reader', email='reader@example.com')
        self.inactive = create_user(
            username='announcement-inactive',
            email='inactive@example.com',
            is_active=False,
        )
        self.client.force_authenticate(self.reader)

    def publish(self, **kwargs):
        return publish_announcement(
            author=self.author,
            data={
                'title': '站点公告',
                'content': '<p><strong>完整公告内容</strong></p>',
                'priority': 0,
                'submission_id': uuid4(),
                **kwargs,
            },
        )

    def system_list(self):
        return self.client.get(reverse('api:check_all_message', args=['system']))

    def unread(self):
        return self.client.get(reverse('api:unread_message')).data['contents']

    def test_publication_notifies_every_existing_account_as_system_and_counts_unread(self):
        entry, created = self.publish()
        self.assertTrue(created)
        notices = Notification.objects.filter(kind=Notification.KIND_SYSTEM)
        self.assertEqual(
            set(notices.values_list('recipient_id', flat=True)),
            {
                self.author.pk,
                self.reader.pk,
                self.inactive.pk,
            },
        )
        self.assertFalse(notices.exclude(actor=None, read_at=None).exists())
        note = notices.get(recipient=self.reader)
        self.assertNotIn('content', note.payload)
        self.assertEqual(note.created_at, entry.created_at)
        self.assertEqual(note.updated_at, entry.created_at)
        item = self.system_list().data['contents']['results'][0]
        self.assertEqual(item['source'], 'announcement')
        self.assertEqual(item['title'], entry.title)
        self.assertEqual(item['content'], entry.content)
        self.assertEqual(item['target_url'], f'/announcements/{entry.pk}')
        self.assertNotIn('created_by', item)
        note.refresh_from_db()
        self.assertIsNone(note.read_at)
        self.assertEqual(
            self.unread(),
            {
                'unread': {'user': 0, 'system': 1, 'like': 0, 'reply': 0},
                'total': 1,
            },
        )

    def test_duplicate_submission_preserves_read_state_and_new_users_get_no_history(self):
        submission_id = uuid4()
        entry, _ = self.publish(submission_id=submission_id)
        note = Notification.objects.get(recipient=self.reader)
        other_client = APIClient()
        other_client.force_authenticate(self.author)
        foreign_read = other_client.post(
            reverse('api:read_notifications'),
            {'ids': [note.pk]},
            format='json',
        )
        self.assertEqual(foreign_read.data['contents']['updated'], 0)
        read_response = self.client.post(
            reverse('api:read_notifications'),
            {'ids': [note.pk]},
            format='json',
        )
        self.assertEqual(read_response.data['contents']['updated'], 1)
        note.refresh_from_db()
        read_at = note.read_at
        newcomer = create_user(username='announcement-newcomer', email='newcomer@example.com')
        repeated, created = self.publish(submission_id=submission_id)
        self.assertFalse(created)
        self.assertEqual(repeated.pk, entry.pk)
        self.assertEqual(Notification.objects.count(), 3)
        self.assertFalse(Notification.objects.filter(recipient=newcomer).exists())
        note.refresh_from_db()
        self.assertEqual(note.read_at, read_at)
        self.assertEqual(self.unread()['total'], 0)

    def test_edit_visibility_and_deletion_use_current_content_without_new_alerts(self):
        entry, _ = self.publish()
        note = Notification.objects.get(recipient=self.reader)
        self.client.post(reverse('api:read_notifications'), {'ids': [note.pk]}, format='json')
        updated = update_announcement(
            entry_id=entry.pk,
            editor=self.author,
            data={
                'title': '修改后的标题',
                'content': '<p>替换后的公告内容</p>',
                'priority': 10,
            },
        )
        item = self.system_list().data['contents']['results'][0]
        self.assertEqual(item['title'], updated.title)
        self.assertEqual(item['content'], updated.content)
        self.assertEqual(item['datetime'], entry.created_at.isoformat())
        set_announcement_visibility(entry_id=entry.pk, visible=False)
        hidden = self.system_list().data['contents']['results'][0]
        self.assertEqual(hidden['title'], '系统通知')
        self.assertEqual(hidden['content'], '[公告已隐藏]')
        self.assertNotIn('target_url', hidden)
        set_announcement_visibility(entry_id=entry.pk, visible=True)
        self.assertEqual(self.system_list().data['contents']['results'][0]['content'], updated.content)
        self.assertEqual(Notification.objects.count(), 3)
        self.assertEqual(self.unread()['total'], 0)
        set_announcement_visibility(entry_id=entry.pk, visible=False)
        delete_announcement(entry_id=entry.pk)
        self.assertFalse(Notification.objects.exists())

    def test_publication_and_notifications_roll_back_together(self):
        with patch(
            'common.announcement_notifications._broadcast', side_effect=RuntimeError('send failed')
        ):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertFalse(GuestbookEntry.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_old_bulletin_admin_first_enable_sends_once_and_edits_hydrate(self):
        model_admin = BulletinsAdmin(Bulletin, AdminSite())
        request = SimpleNamespace(user=self.author)
        bulletin = Bulletin(title='旧公告草稿', content='旧公告正文', publisher=self.author, enabled=False)
        model_admin.save_model(request, bulletin, None, False)
        self.assertFalse(bulletin.system_notification_sent)
        self.assertFalse(Notification.objects.exists())
        bulletin.enabled = True
        model_admin.save_model(request, bulletin, None, True)
        bulletin.refresh_from_db()
        self.assertTrue(bulletin.system_notification_sent)
        self.assertEqual(Notification.objects.count(), 3)
        note = Notification.objects.get(recipient=self.reader)
        self.assertIsNone(note.actor_id)
        self.assertIsNone(note.read_at)
        self.client.post(reverse('api:read_notifications'), {'ids': [note.pk]}, format='json')
        newcomer = create_user(username='bulletin-newcomer', email='bulletin-newcomer@example.com')
        bulletin.title = '旧公告更新标题'
        bulletin.content = '旧公告更新正文'
        model_admin.save_model(request, bulletin, None, True)
        item = self.system_list().data['contents']['results'][0]
        self.assertEqual(item['source'], 'bulletin')
        self.assertEqual(item['title'], bulletin.title)
        self.assertEqual(item['content'], bulletin.content)
        self.assertNotIn('target_url', item)
        self.assertNotIn('created_by', item)
        bulletin.enabled = False
        model_admin.save_model(request, bulletin, None, True)
        self.assertEqual(self.system_list().data['contents']['results'][0]['content'], '[公告已隐藏]')
        bulletin.enabled = True
        model_admin.save_model(request, bulletin, None, True)
        self.assertEqual(Notification.objects.count(), 3)
        self.assertFalse(Notification.objects.filter(recipient=newcomer).exists())
        self.assertEqual(self.unread()['total'], 0)
        model_admin.delete_queryset(request, Bulletin.objects.filter(pk=bulletin.pk))
        self.assertFalse(Notification.objects.exists())

    def test_old_bulletin_enabled_creation_and_stale_form_do_not_reset_send_marker(self):
        model_admin = BulletinsAdmin(Bulletin, AdminSite())
        request = SimpleNamespace(user=self.author)
        bulletin = Bulletin(title='已发布的旧公告', content='公告正文', publisher=self.author)
        model_admin.save_model(request, bulletin, None, False)
        self.assertEqual(Notification.objects.count(), 3)
        stale = Bulletin.objects.get(pk=bulletin.pk)
        stale.system_notification_sent = False
        create_user(username='bulletin-later', email='later@example.com')
        model_admin.save_model(request, stale, None, True)
        self.assertTrue(stale.system_notification_sent)
        self.assertEqual(Notification.objects.count(), 3)
        notify_bulletin_published(stale)
        self.assertEqual(Notification.objects.count(), 3)

    def test_delayed_first_enable_uses_publication_time_and_sorts_above_recent_notes(self):
        bulletin = Bulletin.objects.create(
            title='延迟发布的公告',
            content='公告正文',
            publisher=self.author,
            enabled=False,
        )
        old_time = timezone.now() - timedelta(days=5)
        Bulletin.objects.filter(pk=bulletin.pk).update(create_time=old_time)
        recent_note = Notification.objects.create(
            recipient=self.reader,
            kind=Notification.KIND_SYSTEM,
            payload={'title': '近期系统通知', 'content': '其它事件'},
            dedupe_key='recent-system-event',
        )
        Notification.objects.filter(pk=recent_note.pk).update(
            updated_at=timezone.now() - timedelta(days=1)
        )
        published_at = timezone.now()
        bulletin.enabled = True
        with patch('common.announcement_notifications.timezone.now', return_value=published_at):
            BulletinsAdmin(Bulletin, AdminSite()).save_model(None, bulletin, None, True)
        note = Notification.objects.get(recipient=self.reader, payload__source='bulletin')
        self.assertEqual(note.created_at, published_at)
        self.assertEqual(note.updated_at, published_at)
        self.assertEqual(note.payload['datetime'], published_at.isoformat())
        self.assertEqual(self.system_list().data['contents']['results'][0]['id'], note.pk)

    def test_physical_announcement_deletion_cleans_its_system_notifications(self):
        entry, _ = self.publish()
        GuestbookEntry.all_objects.filter(pk=entry.pk).delete()
        self.assertFalse(Notification.objects.exists())

    def test_bulletin_deletion_does_not_remove_other_kinds_with_same_source(self):
        bulletin = Bulletin.objects.create(title='旧公告', content='正文', publisher=self.author)
        notify_bulletin_published(bulletin)
        unrelated = Notification.objects.create(
            recipient=self.reader,
            kind=Notification.KIND_REPLY,
            payload={'source': 'bulletin', 'bulletin': {'id': bulletin.pk}},
            dedupe_key='other-kind',
        )
        bulletin.delete()
        self.assertEqual(list(Notification.objects.values_list('pk', flat=True)), [unrelated.pk])

    def test_source_hydration_batches_queries_and_does_not_affect_other_system_notes(self):
        entry, _ = self.publish()
        bulletin = Bulletin.objects.create(title='旧公告', content='当前正文', publisher=self.author)
        notify_bulletin_published(bulletin)
        generic = Notification.objects.create(
            recipient=self.reader,
            kind=Notification.KIND_SYSTEM,
            payload={'title': '其它系统事件', 'content': '保留这段正文'},
            dedupe_key='other-system-event',
        )
        notes = list(Notification.objects.filter(recipient=self.reader))
        with self.assertNumQueries(2):
            hydrate_announcement_notifications(notes)
        self.assertEqual(next(note.payload for note in notes if note.pk == generic.pk), generic.payload)
        self.assertEqual(
            next(note.payload for note in notes if note.payload.get('source') == 'announcement')[
                'title'
            ],
            entry.title,
        )
