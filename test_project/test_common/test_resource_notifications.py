from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from common.admin import ResourceUploadRequestAdmin
from common.file.models import ResourceUploadRequest
from common.file.resource_notifications import (
    RESULT_APPROVED,
    RESULT_PUBLISH_FAILED,
    RESULT_REJECTED,
    build_resource_upload_result_message,
    get_resource_public_url,
    notify_resource_upload_result,
)
from common.file.resource_publish import ResourcePublishError
from common.models import Conversation, DirectMessage, Notification
from test_project.common import create_user


@override_settings(
    RESOURCES_WEBSITE_URL='https://resour.nwu.icu',
    FRONTEND_URL='https://nwu.icu',
    WEBSITE_NAME='NWU.ICU',
    EMAIL_HOST_USER='notify@nwu.icu',
)
class ResourceUploadNotificationTests(SimpleTestCase):
    def setUp(self):
        self.reviewer = SimpleNamespace(id=1)
        self.user = SimpleNamespace(
            id=2,
            email='student@example.com',
            college_email=None,
        )
        self.upload_request = SimpleNamespace(
            pk=42,
            target_path='/考试资料/高等数学',
            rejection_reason='目标目录已有同名文件',
            uploaded_by=self.user,
            uploaded_by_id=self.user.id,
        )

    def test_public_url_is_encoded_but_keeps_directory_separators(self):
        self.assertEqual(
            get_resource_public_url('/考试资料/高等 数学'),
            'https://nwu.icu/disk/%E8%80%83%E8%AF%95%E8%B5%84%E6%96%99/'
            '%E9%AB%98%E7%AD%89%20%E6%95%B0%E5%AD%A6',
        )

    def test_approved_message_contains_published_path_and_link(self):
        message = build_resource_upload_result_message(
            self.upload_request,
            RESULT_APPROVED,
        )

        self.assertIn('已审核通过并成功发布', message)
        self.assertIn('/考试资料/高等数学', message)
        self.assertNotIn('查看资料', message)

    def test_publish_failure_message_explains_that_request_was_returned(self):
        message = build_resource_upload_result_message(
            self.upload_request,
            RESULT_PUBLISH_FAILED,
        )

        self.assertIn('发布失败', message)
        self.assertIn('已退回修改', message)
        self.assertIn(self.upload_request.rejection_reason, message)

    @patch('common.admin.approve_resource_upload')
    def test_bulk_approval_queues_publish_workflow(self, approve_resource_upload):
        upload_request = SimpleNamespace(
            pk=42,
            status=ResourceUploadRequest.STATUS_PENDING,
            target_path='/courses',
            reviewed_by=None,
            reviewed_at=None,
            rejection_reason='',
            revision=1,
        )
        filtered_queryset = Mock()
        filtered_queryset.select_related.return_value.prefetch_related.return_value = [upload_request]
        queryset = Mock()
        queryset.filter.return_value = filtered_queryset
        request = SimpleNamespace(user=self.reviewer)
        model_admin = ResourceUploadRequestAdmin(ResourceUploadRequest, AdminSite())
        model_admin.message_user = Mock()

        model_admin.approve_requests(request, queryset)

        approve_resource_upload.assert_called_once_with(
            upload_request_id=42,
            reviewer=self.reviewer,
            expected_revision=1,
            target_path=upload_request.target_path,
        )


@override_settings(WEBSITE_NAME='NWU.ICU', EMAIL_HOST_USER='notify@nwu.icu')
class ResourceLegacyNotificationTests(TestCase):
    def setUp(self):
        self.user = create_user(is_active=True, email='student@example.com')
        self.reviewer = create_user(username='reviewer', email='reviewer@example.com', is_active=True)
        self.upload_request = ResourceUploadRequest.objects.create(
            uploaded_by=self.user,
            target_path='/courses',
            rejection_reason='请补充课程信息',
        )

    @patch('common.file.resource_notifications.send_mail')
    def test_all_results_send_system_notice_and_email(self, send_mail):
        for result in (RESULT_APPROVED, RESULT_PUBLISH_FAILED, RESULT_REJECTED):
            notify_resource_upload_result(self.reviewer, self.upload_request, result)

        self.assertEqual(Notification.objects.count(), 3)
        for notice in Notification.objects.all():
            self.assertEqual(notice.recipient, self.user)
            self.assertEqual(notice.kind, Notification.KIND_SYSTEM)
            self.assertIsNone(notice.actor_id)
            self.assertIsNone(notice.read_at)
            self.assertIn('资料投稿', notice.payload['title'])
            self.assertIn(f'投稿 #{self.upload_request.pk}', notice.payload['content'])
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(DirectMessage.objects.exists())
        self.assertEqual(send_mail.call_count, 3)
        for call in send_mail.call_args_list:
            self.assertEqual(call.args[2], 'notify@nwu.icu')
            self.assertEqual(call.args[3], ['student@example.com'])

    @patch('common.file.resource_notifications.send_mail')
    def test_self_review_and_missing_reviewer_send_system_notices(self, send_mail):
        notify_resource_upload_result(self.user, self.upload_request, RESULT_APPROVED)
        notify_resource_upload_result(None, self.upload_request, RESULT_REJECTED)

        self.assertEqual(Notification.objects.filter(actor__isnull=True, read_at__isnull=True).count(), 2)
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(DirectMessage.objects.exists())

    @patch('common.file.resource_notifications.send_mail')
    def test_repeat_result_preserves_read_notice_and_new_revision_is_unread(self, send_mail):
        notify_resource_upload_result(self.reviewer, self.upload_request, RESULT_REJECTED)
        notice = Notification.objects.get()
        read_at = timezone.now()
        notice.read_at = read_at
        notice.save(update_fields=('read_at',))

        notify_resource_upload_result(None, self.upload_request, RESULT_REJECTED)
        notice.refresh_from_db()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notice.read_at, read_at)

        self.upload_request.revision += 1
        self.upload_request.save(update_fields=('revision', 'updated_at'))
        notify_resource_upload_result(self.reviewer, self.upload_request, RESULT_REJECTED)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(Notification.objects.filter(read_at__isnull=True).count(), 1)
