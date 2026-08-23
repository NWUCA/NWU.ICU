from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MessageDataMigrationTests(TransactionTestCase):
    migrate_from = [('common', '0036_unique_system_chat')]
    migrate_to = [('common', '0038_remove_legacy_chat_models')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        from user.models import User
        Chat = old_apps.get_model('common', 'Chat')
        ChatMessage = old_apps.get_model('common', 'ChatMessage')

        user_a = User.objects.create(username='migration-a', nickname='A', password='!')
        user_b = User.objects.create(username='migration-b', nickname='B', password='!')
        forward = Chat.objects.create(sender_id=user_a.id, receiver_id=user_b.id, classify='user')
        reverse = Chat.objects.create(sender_id=user_b.id, receiver_id=user_a.id, classify='user')
        first = ChatMessage.objects.create(
            chat_item_id=forward.id,
            created_by_id=user_a.id,
            content='first legacy message',
            read=False,
        )
        second = ChatMessage.objects.create(
            chat_item_id=reverse.id,
            created_by_id=user_a.id,
            content='second legacy message',
            read=True,
        )
        system_chat = Chat.objects.create(sender_id=None, receiver_id=user_b.id, classify='system')
        system_message = ChatMessage.objects.create(
            chat_item_id=system_chat.id,
            created_by_id=None,
            content='legacy system notice',
            read=False,
        )
        self.ids = {
            'user_a': user_a.id,
            'user_b': user_b.id,
            'first': first.id,
            'second': second.id,
            'system': system_message.id,
        }

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)

    def test_reverse_chats_messages_read_gap_and_system_notice_are_migrated(self):
        from common.models import Conversation, ConversationParticipant, DirectMessage, Notification

        self.assertEqual(Conversation.objects.count(), 1)
        conversation = Conversation.objects.get()
        self.assertEqual(
            list(DirectMessage.objects.filter(conversation=conversation).values_list('id', 'content')),
            [
                (self.ids['first'], 'first legacy message'),
                (self.ids['second'], 'second legacy message'),
            ],
        )
        self.assertEqual(conversation.last_message_id, self.ids['second'])
        participant_b = ConversationParticipant.objects.get(
            conversation=conversation,
            user_id=self.ids['user_b'],
        )
        # The highest read message is a watermark, so an older unread gap is
        # intentionally considered read under the new conversation semantics.
        self.assertEqual(participant_b.last_read_message_id, self.ids['second'])
        system_notice = Notification.objects.get(
            dedupe_key=f"legacy-system-message:{self.ids['system']}"
        )
        self.assertEqual(system_notice.kind, Notification.KIND_SYSTEM)
        self.assertEqual(system_notice.payload['content'], 'legacy system notice')
        table_names = connection.introspection.table_names()
        self.assertNotIn('common_chatlike', table_names)
        self.assertNotIn('common_chatreply', table_names)
        self.assertNotIn('common_chatmessage', table_names)
        self.assertNotIn('common_chat', table_names)
        next_message = DirectMessage.objects.create(
            conversation=conversation,
            sender_id=self.ids['user_a'],
            content='created after migration',
        )
        self.assertGreater(next_message.id, self.ids['second'])
        next_notice = Notification.objects.create(
            recipient_id=self.ids['user_b'],
            kind=Notification.KIND_SYSTEM,
            dedupe_key='created-after-migration',
            payload={'title': 'new'},
        )
        self.assertGreater(next_notice.id, system_notice.id)


class MessageMigrationAtomicFailureTests(TransactionTestCase):
    migrate_from = [('common', '0036_unique_system_chat')]
    migrate_to = [('common', '0038_remove_legacy_chat_models')]

    def test_validation_failure_keeps_every_legacy_table(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        ChatMessage = old_apps.get_model('common', 'ChatMessage')
        ChatMessage.objects.create(chat_item_id=None, created_by_id=None, content='orphaned')

        executor = MigrationExecutor(connection)
        with self.assertRaises(RuntimeError):
            executor.migrate(self.migrate_to)

        table_names = connection.introspection.table_names()
        self.assertIn('common_chatlike', table_names)
        self.assertIn('common_chatreply', table_names)
        self.assertIn('common_chatmessage', table_names)
        self.assertIn('common_chat', table_names)

        # Restore the latest schema so TransactionTestCase can flush the test
        # database using the current model state during teardown.
        ChatMessage.objects.filter(chat_item_id=None).delete()
        MigrationExecutor(connection).migrate(self.migrate_to)
