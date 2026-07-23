import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone
from django.utils.html import format_html

from common.file.models import ResourceUploadFile, ResourceUploadRequest
from settings import settings
from .models import Announcement, Bulletin, About, Chat, ChatMessage


logger = logging.getLogger(__name__)


class ResourceUploadActionForm(ActionForm):
    rejection_reason = forms.CharField(label='拒绝理由', required=False, max_length=2000)


class ResourceUploadFileInline(admin.TabularInline):
    model = ResourceUploadFile
    extra = 0
    can_delete = False
    fields = ('relative_path', 'size', 'download_link')
    readonly_fields = fields

    def download_link(self, obj):
        if not obj.pk or not obj.file:
            return '-'
        try:
            return format_html('<a href="{}" download>下载</a>', obj.file.url)
        except ValueError:
            return '文件已删除'

    download_link.short_description = '文件'


@admin.register(ResourceUploadRequest)
class ResourceUploadRequestAdmin(admin.ModelAdmin):
    action_form = ResourceUploadActionForm
    actions = ('approve_requests', 'reject_requests')
    inlines = (ResourceUploadFileInline,)
    list_display = (
        'id', 'uploaded_by', 'target_path', 'status', 'total_size', 'created_at', 'reviewed_by', 'reviewed_at',
        'files_deleted_at',
    )
    list_filter = ('status', 'created_at', 'reviewed_at', 'files_deleted_at')
    search_fields = ('uploaded_by__username', 'uploaded_by__nickname', 'target_path', 'files__relative_path')
    readonly_fields = (
        'uploaded_by', 'target_path', 'status', 'total_size', 'created_at', 'reviewed_at', 'reviewed_by',
        'rejection_reason', 'files_deleted_at',
    )
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        current_size = ResourceUploadRequest.objects.filter(files_deleted_at__isnull=True).aggregate(
            total=Sum('total_size')
        )['total'] or 0
        extra_context = extra_context or {}
        extra_context['title'] = f'上传请求（当前暂存文件总大小：{self.format_size(current_size)}）'
        return super().changelist_view(request, extra_context=extra_context)

    @staticmethod
    def format_size(size):
        value = float(size)
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if value < 1024 or unit == 'TB':
                return f'{value:.2f} {unit}'
            value /= 1024

    @admin.action(description='通过所选的未审核请求')
    def approve_requests(self, request, queryset):
        pending = queryset.filter(status=ResourceUploadRequest.STATUS_PENDING)
        updated = pending.update(
            status=ResourceUploadRequest.STATUS_APPROVED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
            rejection_reason='',
        )
        self.message_user(request, f'已通过 {updated} 个上传请求。', messages.SUCCESS)

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
            self.notify_rejection(request.user, upload_request)
        self.message_user(request, f'已拒绝 {len(upload_requests)} 个上传请求。', messages.SUCCESS)

    @staticmethod
    def notify_rejection(reviewer, upload_request):
        content = f'你的资料上传请求 #{upload_request.pk} 已被拒绝。理由：{upload_request.rejection_reason}'
        if reviewer != upload_request.uploaded_by:
            chat, unused = Chat.get_or_create_chat(
                sender=reviewer, receiver=upload_request.uploaded_by, classify='user'
            )
            ChatMessage.objects.create(content=content, chat_item=chat, created_by=reviewer)
        recipient = upload_request.uploaded_by.email or upload_request.uploaded_by.college_email
        if recipient:
            try:
                send_mail(
                    f'{settings.WEBSITE_NAME} 资料上传请求审核结果',
                    content,
                    settings.EMAIL_HOST_USER,
                    [recipient],
                    fail_silently=False,
                )
            except Exception:
                logger.exception('Failed to send resource upload rejection email to user %s', upload_request.uploaded_by_id)


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
