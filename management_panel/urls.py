from django.urls import path
from .resource_files import ManagementFileActionView, ManagementFileListView, ManagementFileUploadView, ManagementTrashView
from .resource_tools import (ManagementResourceOperationsView, ManagementResourceReadmeView,
                             ManagementResourceAccessView, ManagementResourceIndexView,
                             ManagementResourceAuditView, ManagementResourceStatisticsView)

from .views import (
    ManagementAnnouncementDetailView,
    ManagementAnnouncementVisibilityView,
    ManagementAnnouncementView,
    ManagementReportListView,
    ManagementReportResolveView,
    ManagementResourceUploadDetailView,
    ManagementResourceUploadFileDownloadView,
    ManagementResourceUploadListView,
    ManagementResourceUploadBlacklistView,
    ManagementResourceDirectoryView,
    ManagementSessionView,
    ManagementTelegramNotificationSettingsView,
    PasskeyAuthenticationOptionsView,
    PasskeyAuthenticationVerifyView,
    PasskeyRegistrationOptionsView,
    PasskeyRegistrationVerifyView,
)


urlpatterns = [
    path('resources/operations/', ManagementResourceOperationsView.as_view(), name='management-resource-operations'),
    path('resources/readme/', ManagementResourceReadmeView.as_view(), name='management-resource-readme'),
    path('resources/access/', ManagementResourceAccessView.as_view(), name='management-resource-access'),
    path('resources/index/', ManagementResourceIndexView.as_view(), name='management-resource-index'),
    path('resources/audit/', ManagementResourceAuditView.as_view(), name='management-resource-audit'),
    path('resources/statistics/', ManagementResourceStatisticsView.as_view(), name='management-resource-statistics'),
    path('resources/', ManagementFileListView.as_view(), name='management-resource-files'),
    path('resources/upload/', ManagementFileUploadView.as_view(), name='management-resource-file-upload'),
    path('resources/action/', ManagementFileActionView.as_view(), name='management-resource-file-action'),
    path('resources/trash/', ManagementTrashView.as_view(), name='management-resource-trash'),
    path('session/', ManagementSessionView.as_view(), name='management-session'),
    path('notifications/telegram/', ManagementTelegramNotificationSettingsView.as_view(), name='management-telegram-notifications'),
    path('passkeys/authentication/options/', PasskeyAuthenticationOptionsView.as_view(), name='passkey-auth-options'),
    path('passkeys/authentication/verify/', PasskeyAuthenticationVerifyView.as_view(), name='passkey-auth-verify'),
    path('passkeys/registration/options/', PasskeyRegistrationOptionsView.as_view(), name='passkey-register-options'),
    path('passkeys/registration/verify/', PasskeyRegistrationVerifyView.as_view(), name='passkey-register-verify'),
    path('reports/', ManagementReportListView.as_view(), name='management-reports'),
    path('reports/<int:report_id>/resolve/', ManagementReportResolveView.as_view(), name='management-report-resolve'),
    path('announcements/', ManagementAnnouncementView.as_view(), name='management-announcements'),
    path(
        'announcements/<int:entry_id>/',
        ManagementAnnouncementDetailView.as_view(),
        name='management-announcement-detail',
    ),
    path(
        'announcements/<int:entry_id>/visibility/',
        ManagementAnnouncementVisibilityView.as_view(),
        name='management-announcement-visibility',
    ),
    path('uploads/', ManagementResourceUploadListView.as_view(), name='management-uploads'),
    path('uploads/blacklist/', ManagementResourceUploadBlacklistView.as_view(), name='management-upload-blacklist'),
    path('uploads/directories/', ManagementResourceDirectoryView.as_view(), name='management-upload-directories'),
    path('uploads/<int:request_id>/', ManagementResourceUploadDetailView.as_view(), name='management-upload-detail'),
    path('uploads/files/<int:file_id>/download/', ManagementResourceUploadFileDownloadView.as_view(), name='management-upload-file'),
]
