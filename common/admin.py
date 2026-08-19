import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from common.file.models import ResourceUploadFile, ResourceUploadRequest
from common.file.resource_notifications import (
    RESULT_APPROVED,
    RESULT_PUBLISH_FAILED,
    RESULT_REJECTED,
    notify_resource_upload_result,
)
from common.file.resource_publish import ResourcePublishError, publish_resource_upload
from utils.utils import format_file_size
from .models import Announcement, Bulletin, About


logger = logging.getLogger(__name__)


class ResourceUploadActionForm(ActionForm):
    rejection_reason = forms.CharField(label='拒绝理由', required=False, max_length=2000)


class ResourceUploadFileInline(admin.TabularInline):
    model = ResourceUploadFile
    extra = 0
    can_delete = False
    fields = ('relative_path', 'size_display', 'download_link')
    readonly_fields = fields

    @admin.display(description='大小')
    def size_display(self, obj):
        return format_file_size(obj.size)

    def download_link(self, obj):
        if not obj.pk or not obj.file:
            return '-'
        return format_html(
            '<a href="{}">下载</a>',
            reverse('api:resource-upload-file-download', args=(obj.pk,)),
        )

    download_link.short_description = '文件'


@admin.register(ResourceUploadRequest)
class ResourceUploadRequestAdmin(admin.ModelAdmin):
    action_form = ResourceUploadActionForm
    actions = ('approve_requests', 'reject_requests')
    inlines = (ResourceUploadFileInline,)
    list_display = (
        'id', 'uploaded_by', 'target_path', 'creates_new_folder', 'file_links', 'status', 'total_size_display',
        'created_at', 'reviewed_by', 'reviewed_at', 'files_deleted_at',
    )
    list_filter = ('status', 'created_at', 'reviewed_at', 'files_deleted_at')
    search_fields = ('uploaded_by__username', 'uploaded_by__nickname', 'target_path', 'files__relative_path')
    readonly_fields = (
        'uploaded_by', 'target_path', 'creates_new_folder', 'status', 'total_size_display', 'created_at',
        'reviewed_at', 'reviewed_by', 'rejection_reason', 'files_deleted_at',
    )
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('files')

    @admin.display(description='投稿文件')
    def file_links(self, obj):
        files = list(obj.files.all())
        if not files:
            return '-'
        return format_html_join(
            '',
            '<div><a href="{}">{}</a> <span style="color:#666">({})</span></div>',
            (
                (
                    reverse('api:resource-upload-file-download', args=(upload_file.pk,)),
                    upload_file.relative_path,
                    format_file_size(upload_file.size),
                )
                for upload_file in files
            ),
        )

    @admin.display(description='总大小', ordering='total_size')
    def total_size_display(self, obj):
        return format_file_size(obj.total_size)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        current_size = ResourceUploadRequest.objects.filter(files_deleted_at__isnull=True).aggregate(
            total=Sum('total_size')
        )['total'] or 0
        extra_context = extra_context or {}
        extra_context['title'] = f'上传请求（当前暂存文件总大小：{format_file_size(current_size)}）'
        return super().changelist_view(request, extra_context=extra_context)

    @admin.action(description='通过所选的未审核请求')
    def approve_requests(self, request, queryset):
        pending_requests = list(
            queryset.filter(status=ResourceUploadRequest.STATUS_PENDING)
            .select_related('uploaded_by')
            .prefetch_related('files')
        )
        approved_count = 0
        failed_count = 0
        for upload_request in pending_requests:
            try:
                published_entries = publish_resource_upload(upload_request)
            except ResourcePublishError as error:
                failed_count += 1
                logger.exception('Failed to publish resource upload request %s', upload_request.pk)
                upload_request.status = ResourceUploadRequest.STATUS_REJECTED
                upload_request.reviewed_by = request.user
                upload_request.reviewed_at = timezone.now()
                upload_request.rejection_reason = f'系统发布时发生错误：{error}'
                upload_request.save(update_fields=(
                    'status', 'reviewed_by', 'reviewed_at', 'rejection_reason',
                ))
                notify_resource_upload_result(
                    request.user,
                    upload_request,
                    RESULT_PUBLISH_FAILED,
                )
                self.message_user(
                    request,
                    f'请求 #{upload_request.pk} 发布失败，已退回并通知投稿用户：{error}',
                    messages.ERROR,
                )
                continue

            upload_request.status = ResourceUploadRequest.STATUS_APPROVED
            upload_request.reviewed_by = request.user
            upload_request.reviewed_at = timezone.now()
            upload_request.rejection_reason = ''
            upload_request.save(update_fields=(
                'status', 'reviewed_by', 'reviewed_at', 'rejection_reason',
            ))
            notify_resource_upload_result(request.user, upload_request, RESULT_APPROVED)
            approved_count += 1
            logger.info(
                'Published resource upload request %s (%s files)',
                upload_request.pk,
                len(published_entries),
            )

        if approved_count:
            self.message_user(
                request,
                f'已复制文件并通过 {approved_count} 个上传请求。原投稿文件将在 30 天后清理。',
                messages.SUCCESS,
            )
        if failed_count:
            self.message_user(
                request,
                f'{failed_count} 个请求发布失败，均已退回并通知投稿用户。',
                messages.WARNING,
            )

    @admin.action(description='拒绝所选的未审核请求')
    def reject_requests(self, request, queryset):
        reason = request.POST.get('rejection_reason', '').strip()
        if not reason:
            self.message_user(request, '拒绝上传请求时必须填写拒绝理由。', messages.ERROR)
            return
        upload_requests = list(
            queryset.filter(status=ResourceUploadRequest.STATUS_PENDING).select_related('uploaded_by')
        )
        now = timezone.now()
        for upload_request in upload_requests:
            upload_request.status = ResourceUploadRequest.STATUS_REJECTED
            upload_request.reviewed_by = request.user
            upload_request.reviewed_at = now
            upload_request.rejection_reason = reason
            upload_request.save(update_fields=('status', 'reviewed_by', 'reviewed_at', 'rejection_reason'))
            notify_resource_upload_result(request.user, upload_request, RESULT_REJECTED)
        self.message_user(request, f'已拒绝 {len(upload_requests)} 个上传请求。', messages.SUCCESS)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('content', 'type', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')


@admin.register(Bulletin)
class BulletinsAdmin(admin.ModelAdmin):
    list_display = ('content', 'title', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')


@admin.register(About)
class AboutAdmin(admin.ModelAdmin):
    list_display = ('content', 'update_time', 'create_time')
    readonly_fields = ('create_time', 'update_time')
