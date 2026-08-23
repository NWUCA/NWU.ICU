from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase, override_settings

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


@override_settings(
    RESOURCES_WEBSITE_URL='https://resour.nwu.icu',
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
            'https://resour.nwu.icu/%E8%80%83%E8%AF%95%E8%B5%84%E6%96%99/'
            '%E9%AB%98%E7%AD%89%20%E6%95%B0%E5%AD%A6',
        )

    def test_approved_message_contains_published_path_and_link(self):
        message = build_resource_upload_result_message(
            self.upload_request,
            RESULT_APPROVED,
        )

        self.assertIn('已审核通过并成功发布', message)
        self.assertIn('/考试资料/高等数学', message)
        self.assertIn('https://resour.nwu.icu/', message)

    def test_publish_failure_message_explains_that_request_was_returned(self):
        message = build_resource_upload_result_message(
            self.upload_request,
            RESULT_PUBLISH_FAILED,
        )

        self.assertIn('发布失败', message)
        self.assertIn('已退回修改', message)
        self.assertIn(self.upload_request.rejection_reason, message)

    @patch('common.file.resource_notifications.send_mail')
    @patch('common.file.resource_notifications.send_direct_message')
    def test_all_results_send_site_message_and_email(
            self, send_site_message, send_mail):

        for result in (RESULT_APPROVED, RESULT_PUBLISH_FAILED, RESULT_REJECTED):
            notify_resource_upload_result(self.reviewer, self.upload_request, result)

        self.assertEqual(send_site_message.call_count, 3)
        self.assertEqual(send_mail.call_count, 3)
        for call in send_mail.call_args_list:
            self.assertEqual(call.args[2], 'notify@nwu.icu')
            self.assertEqual(call.args[3], ['student@example.com'])

    @patch('common.admin.notify_resource_upload_result')
    @patch('common.admin.publish_resource_upload')
    def test_publish_failure_is_returned_and_user_is_notified(
            self, publish_resource_upload, notify_result):
        publish_resource_upload.side_effect = ResourcePublishError('目标文件已存在')
        upload_request = SimpleNamespace(
            pk=42,
            status=ResourceUploadRequest.STATUS_PENDING,
            reviewed_by=None,
            reviewed_at=None,
            rejection_reason='',
            save=Mock(),
        )
        filtered_queryset = Mock()
        filtered_queryset.select_related.return_value.prefetch_related.return_value = [upload_request]
        queryset = Mock()
        queryset.filter.return_value = filtered_queryset
        request = SimpleNamespace(user=self.reviewer)
        model_admin = ResourceUploadRequestAdmin(ResourceUploadRequest, AdminSite())
        model_admin.message_user = Mock()

        model_admin.approve_requests(request, queryset)

        self.assertEqual(upload_request.status, ResourceUploadRequest.STATUS_REJECTED)
        self.assertIn('目标文件已存在', upload_request.rejection_reason)
        upload_request.save.assert_called_once()
        notify_result.assert_called_once_with(
            self.reviewer,
            upload_request,
            RESULT_PUBLISH_FAILED,
        )
