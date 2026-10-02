from datetime import timedelta
from importlib import import_module

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from test_project.common import create_user


def restore_latest_schema():
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


class AnnouncementNotificationMigrationTests(TransactionTestCase):
    migrate_from = [
        ('common', '0047_resource_archives'),
        ('guestbook', '0007_announcement_management_fields'),
    ]
    migrate_to = [('common', '0048_announcement_system_notifications')]

    def setUp(self):
        super().setUp()
        self.addCleanup(restore_latest_schema)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        GuestbookEntry = old_apps.get_model('guestbook', 'GuestbookEntry')
        Bulletin = old_apps.get_model('common', 'Bulletin')
        Notification = old_apps.get_model('common', 'Notification')
        self.publisher = create_user(username='migration-publisher', email='publisher@example.com')
        self.reader = create_user(username='migration-reader', email='reader@example.com', is_active=False)
        self.announcement_time = timezone.now() - timedelta(days=3)
        self.bulletin_time = timezone.now() - timedelta(days=4)
        self.existing_time = timezone.now() - timedelta(days=2)

        entry = GuestbookEntry.objects.create(
            author_id=self.publisher.pk, board='announcement', title='历史新公告', content='<p>当前内容</p>',
        )
        GuestbookEntry.objects.filter(pk=entry.pk).update(created_at=self.announcement_time)
        self.announcement_id = entry.pk
        GuestbookEntry.objects.create(
            author_id=self.publisher.pk, board='announcement', title='隐藏', content='不可见', is_visible=False,
        )
        GuestbookEntry.objects.create(
            author_id=self.publisher.pk, board='announcement', title='删除', content='不可见', is_deleted=True,
        )
        GuestbookEntry.objects.create(
            author_id=self.publisher.pk, board='announcement', parent_id=entry.pk,
            root_id=entry.pk, content='公告回复',
        )
        GuestbookEntry.objects.create(author_id=self.publisher.pk, board='guestbook', content='普通留言')
        bulletin = Bulletin.objects.create(
            title='历史旧公告', content='旧公告内容', publisher_id=self.publisher.pk,
        )
        Bulletin.objects.filter(pk=bulletin.pk).update(create_time=self.bulletin_time)
        self.bulletin_id = bulletin.pk
        self.hidden_bulletin_id = Bulletin.objects.create(
            title='历史禁用公告', content='不可见', publisher_id=self.publisher.pk, enabled=False,
        ).pk
        self.existing_payload = {'title': '已有通知', 'content': '保留原内容'}
        existing = Notification.objects.create(
            recipient_id=self.publisher.pk, actor_id=self.publisher.pk, kind='system',
            dedupe_key=f'announcement:publish:{entry.pk}:{self.publisher.pk}',
            payload=self.existing_payload,
        )
        Notification.objects.filter(pk=existing.pk).update(
            created_at=self.existing_time, updated_at=self.existing_time,
        )
        self.existing_id = existing.pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def test_backfill_includes_both_visible_sources_and_preserves_existing_alerts(self):
        Notification = self.apps.get_model('common', 'Notification')
        Bulletin = self.apps.get_model('common', 'Bulletin')
        self.assertEqual(Notification.objects.count(), 4)
        existing = Notification.objects.get(pk=self.existing_id)
        self.assertIsNone(existing.read_at)
        self.assertEqual(existing.actor_id, self.publisher.pk)
        self.assertEqual(existing.payload, self.existing_payload)
        self.assertEqual(existing.created_at, self.existing_time)
        self.assertEqual(existing.updated_at, self.existing_time)

        for note in Notification.objects.exclude(pk=self.existing_id):
            self.assertIsNotNone(note.read_at)
            self.assertIsNone(note.actor_id)
            self.assertEqual(note.kind, 'system')
            published_at = self.announcement_time if note.payload['source'] == 'announcement' else self.bulletin_time
            self.assertEqual(note.created_at, published_at)
            self.assertEqual(note.updated_at, published_at)
            self.assertEqual(note.payload['datetime'], published_at.isoformat())
            self.assertNotIn('title', note.payload)
            self.assertNotIn('content', note.payload)
        self.assertFalse(Bulletin.objects.filter(system_notification_sent=False).exists())

    def test_repeating_backfill_is_idempotent_and_keeps_chronological_order(self):
        Notification = self.apps.get_model('common', 'Notification')
        before = list(Notification.objects.order_by('pk').values())
        migration = import_module('common.migrations.0048_announcement_system_notifications')
        with connection.schema_editor() as schema_editor:
            migration.backfill_announcement_notifications(self.apps, schema_editor)
        self.assertEqual(list(Notification.objects.order_by('pk').values()), before)
        self.assertEqual(list(Notification.objects.filter(
            recipient_id=self.reader.pk,
        ).order_by('-updated_at', '-id').values_list('payload', flat=True)), [
            {
                'source': 'announcement', 'guestbook': {'root_id': self.announcement_id},
                'datetime': self.announcement_time.isoformat(),
            },
            {
                'source': 'bulletin', 'bulletin': {'id': self.bulletin_id},
                'datetime': self.bulletin_time.isoformat(),
            },
        ])
        newcomer = create_user(username='after-backfill', email='after@example.com')
        self.assertFalse(Notification.objects.filter(recipient_id=newcomer.pk).exists())

    def test_old_hidden_bulletin_does_not_send_when_shown_after_migration(self):
        from common.announcement_notifications import notify_bulletin_published
        from common.models import Bulletin, Notification

        bulletin = Bulletin.objects.get(pk=self.hidden_bulletin_id)
        bulletin.enabled = True
        bulletin.save()
        notify_bulletin_published(bulletin)
        self.assertEqual(Notification.objects.count(), 4)
