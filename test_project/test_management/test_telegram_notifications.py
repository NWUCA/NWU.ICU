import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from management_panel.models import (
    AdminPasskeyCredential,
    AdminPasskeyState,
    TelegramNotificationSettings,
)
from management_panel.security import (
    ELEVATED_CREDENTIAL_KEY,
    ELEVATED_REVISION_KEY,
    ELEVATED_UNTIL_KEY,
)
from management_panel.telegram_notifications import (
    EVENT_SETTING_FIELDS,
    _enqueue,
    send_mail_with_telegram_alert,
)
from test_project.common import create_user


class TelegramNotificationSettingsApiTests(APITestCase):
    def setUp(self):
        self.staff = create_user(
            username='telegram-settings-admin',
            email='telegram-settings-admin@example.com',
            is_staff=True,
            is_superuser=True,
        )
        credential = AdminPasskeyCredential.objects.create(
            user=self.staff,
            name='Test key',
            credential_id=b'telegram-settings-key',
            public_key=b'public-key',
        )
        state = AdminPasskeyState.objects.create(user=self.staff)
        self.client = APIClient()
        self.client.force_login(self.staff)
        session = self.client.session
        session[ELEVATED_UNTIL_KEY] = time.time() + 600
        session[ELEVATED_CREDENTIAL_KEY] = credential.pk
        session[ELEVATED_REVISION_KEY] = state.revision
        session.save()
        self.url = reverse('api:management-telegram-notifications')

    def test_get_creates_enabled_defaults_and_post_updates_each_switch(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['contents'], {
            'user_registration_enabled': True,
            'guestbook_entry_enabled': True,
            'course_review_enabled': True,
            'reply_enabled': True,
        })

        updated = {
            'user_registration_enabled': False,
            'guestbook_entry_enabled': True,
            'course_review_enabled': False,
            'reply_enabled': True,
        }
        response = self.client.post(self.url, updated, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['contents'], updated)
        stored = TelegramNotificationSettings.objects.get(pk=1)
        for field, expected in updated.items():
            self.assertEqual(getattr(stored, field), expected)


@override_settings(TELEGRAM_BOT_API_TOKEN='token', TELEGRAM_CHAT_ID='chat')
class TelegramNotificationDispatchTests(TestCase):
    def test_each_event_uses_its_own_switch(self):
        switches = TelegramNotificationSettings.objects.create(
            user_registration_enabled=False,
            guestbook_entry_enabled=False,
            course_review_enabled=False,
            reply_enabled=False,
        )
        with patch('management_panel.telegram_notifications.telegram_notification_executor.submit') as submit:
            for event, field in EVENT_SETTING_FIELDS.items():
                setattr(switches, field, True)
                switches.save()
                _enqueue(event, event)
                submit.assert_called_once()
                submit.reset_mock()
                setattr(switches, field, False)
                switches.save()
                _enqueue(event, event)
                submit.assert_not_called()


class EmailFailureAlertTests(SimpleTestCase):
    @patch('management_panel.telegram_notifications.notify_email_delivery_failure')
    def test_email_exception_alerts_telegram_and_preserves_original_error(self, notify):
        sender = Mock()
        sender.side_effect = OSError('smtp unavailable')

        with self.assertRaisesRegex(OSError, 'smtp unavailable'):
            send_mail_with_telegram_alert(
                sender,
                subject='注册邮件',
                message='body',
                from_email='notify@example.com',
                recipient_list=['student@example.com'],
                alert_context='用户注册激活邮件',
            )

        notify.assert_called_once_with(
            subject='注册邮件',
            recipients=['student@example.com'],
            error=sender.side_effect,
            context='用户注册激活邮件',
        )

    @patch('management_panel.telegram_notifications.notify_email_delivery_failure')
    def test_zero_delivery_alerts_telegram(self, notify):
        sender = Mock()
        sender.return_value = 0

        result = send_mail_with_telegram_alert(
            sender,
            '投稿成功',
            'body',
            'notify@example.com',
            ['student@example.com'],
            alert_context='资料投稿审核结果邮件',
        )

        self.assertEqual(result, 0)
        notify.assert_called_once()
