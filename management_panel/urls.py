from django.urls import path

from .views import (
    ManagementAnnouncementView,
    ManagementReportListView,
    ManagementReportResolveView,
    ManagementResourceUploadDetailView,
    ManagementResourceUploadFileDownloadView,
    ManagementResourceUploadListView,
    ManagementSessionView,
    PasskeyAuthenticationOptionsView,
    PasskeyAuthenticationVerifyView,
    PasskeyRegistrationOptionsView,
    PasskeyRegistrationVerifyView,
)


urlpatterns = [
    path('session/', ManagementSessionView.as_view(), name='management-session'),
    path('passkeys/authentication/options/', PasskeyAuthenticationOptionsView.as_view(), name='passkey-auth-options'),
    path('passkeys/authentication/verify/', PasskeyAuthenticationVerifyView.as_view(), name='passkey-auth-verify'),
    path('passkeys/registration/options/', PasskeyRegistrationOptionsView.as_view(), name='passkey-register-options'),
    path('passkeys/registration/verify/', PasskeyRegistrationVerifyView.as_view(), name='passkey-register-verify'),
    path('reports/', ManagementReportListView.as_view(), name='management-reports'),
    path('reports/<int:report_id>/resolve/', ManagementReportResolveView.as_view(), name='management-report-resolve'),
    path('announcements/', ManagementAnnouncementView.as_view(), name='management-announcements'),
    path('uploads/', ManagementResourceUploadListView.as_view(), name='management-uploads'),
    path('uploads/<int:request_id>/', ManagementResourceUploadDetailView.as_view(), name='management-upload-detail'),
    path('uploads/files/<int:file_id>/download/', ManagementResourceUploadFileDownloadView.as_view(), name='management-upload-file'),
]

