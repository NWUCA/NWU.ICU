import logging

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from common.file.models import ResourceUploadFile, ResourceUploadRequest
from common.file.admin import AttachmentReferenceAdminMixin
from common.file.resource_workflow import (
    ResourceReviewError,
    approve_resource_upload,
    reject_resource_upload,
    retry_resource_publish,
)
from utils.utils import format_file_size
from .models import Announcement, Bulletin, About


logger = logging.getLogger(__name__)


class ResourceUploadActionForm(ActionForm):
    rejection_reason = forms.CharField(label='拒绝理由', required=False, max_length=2000)


class ResourceUploadReviewForm(forms.Form):
    ACTION_APPROVE = 'approve'
    ACTION_REJECT = 'reject'
    ACTION_RETRY = 'retry'
    action = forms.ChoiceField(choices=(
        (ACTION_APPROVE, '通过并发布'),
        (ACTION_REJECT, '拒绝并通知'),
        (ACTION_RETRY, '重新发布'),
    ), widget=forms.HiddenInput)
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    target_path = forms.CharField(label='最终目标目录', required=False, max_length=2048)
    rejection_reason = forms.CharField(label='拒绝理由', required=False, max_length=2000, widget=forms.Textarea)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('action') in {self.ACTION_APPROVE, self.ACTION_RETRY} and not cleaned.get('target_path', '').strip():
            self.add_error('target_path', '发布投稿时必须填写最终目标目录')
        if cleaned.get('action') == self.ACTION_REJECT and not cleaned.get('rejection_reason', '').strip():
            self.add_error('rejection_reason', '拒绝投稿时必须填写理由')
        return cleaned


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
        'id', 'uploaded_by', 'target_path', 'creates_new_folder', 'file_links', 'status', 'revision', 'review_link', 'total_size_display',
        'created_at', 'reviewed_by', 'reviewed_at', 'files_deleted_at',
    )
    list_filter = ('status', 'created_at', 'reviewed_at', 'files_deleted_at')
    search_fields = ('uploaded_by__username', 'uploaded_by__nickname', 'target_path', 'files__relative_path')
    readonly_fields = (
        'uploaded_by', 'target_path', 'creates_new_folder', 'status', 'total_size_display', 'created_at',
        'revision', 'updated_at', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'publish_error', 'files_deleted_at',
    )
    date_hierarchy = 'created_at'

    def has_module_permission(self, request):
        return request.user.has_perm('common.review_resource_uploads')

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('common.review_resource_uploads')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('common.review_resource_uploads')

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('files')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:object_id>/review/',
                self.admin_site.admin_view(self.review_view),
                name='common_resourceuploadrequest_review',
            ),
        ]
        return custom_urls + urls

    @admin.display(description='审核')
    def review_link(self, obj):
        return format_html('<a href="{}">打开审核页</a>', reverse('admin:common_resourceuploadrequest_review', args=(obj.pk,)))

    def review_view(self, request, object_id):
        if not request.user.has_perm('common.review_resource_uploads'):
            raise PermissionDenied
        upload_request = self.get_queryset(request).filter(pk=object_id).first()
        if upload_request is None:
            self.message_user(request, '投稿不存在', messages.ERROR)
            return redirect('admin:common_resourceuploadrequest_changelist')
        if request.method == 'POST':
            form = ResourceUploadReviewForm(request.POST)
            if form.is_valid():
                try:
                    action = form.cleaned_data['action']
                    if action == ResourceUploadReviewForm.ACTION_APPROVE:
                        approve_resource_upload(
                            upload_request_id=upload_request.pk,
                            reviewer=request.user,
                            expected_revision=form.cleaned_data['expected_revision'],
                            target_path=form.cleaned_data['target_path'],
                        )
                        self.message_user(request, '已进入发布队列。', messages.SUCCESS)
                    elif action == ResourceUploadReviewForm.ACTION_REJECT:
                        reject_resource_upload(
                            upload_request_id=upload_request.pk,
                            reviewer=request.user,
                            expected_revision=form.cleaned_data['expected_revision'],
                            reason=form.cleaned_data['rejection_reason'],
                        )
                        self.message_user(request, '投稿已拒绝，通知已进入发送队列。', messages.SUCCESS)
                    else:
                        retry_resource_publish(
                            upload_request_id=upload_request.pk,
                            reviewer=request.user,
                            expected_revision=form.cleaned_data['expected_revision'],
                            target_path=form.cleaned_data['target_path'],
                        )
                        self.message_user(request, '已重新进入发布队列。', messages.SUCCESS)
                    return redirect('admin:common_resourceuploadrequest_review', object_id=upload_request.pk)
                except ResourceReviewError as error:
                    form.add_error(None, str(error))
        else:
            form = ResourceUploadReviewForm(initial={
                'expected_revision': upload_request.revision,
                'target_path': upload_request.target_path,
            })
        context = {
            **self.admin_site.each_context(request),
            'title': f'审核投稿 #{upload_request.pk}',
            'upload_request': upload_request,
            'form': form,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/common/resourceuploadrequest/review.html', context)

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
        queued_count = 0
        for upload_request in pending_requests:
            try:
                approve_resource_upload(
                    upload_request_id=upload_request.pk,
                    reviewer=request.user,
                    expected_revision=upload_request.revision,
                    target_path=upload_request.target_path,
                )
                queued_count += 1
            except ResourceReviewError as error:
                self.message_user(request, f'请求 #{upload_request.pk} 未进入发布队列：{error}', messages.ERROR)
        if queued_count:
            self.message_user(
                request,
                f'已将 {queued_count} 个上传请求加入发布队列。',
                messages.SUCCESS,
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
        for upload_request in upload_requests:
            try:
                reject_resource_upload(
                    upload_request_id=upload_request.pk,
                    reviewer=request.user,
                    expected_revision=upload_request.revision,
                    reason=reason,
                )
            except ResourceReviewError as error:
                self.message_user(request, f'请求 #{upload_request.pk} 未能拒绝：{error}', messages.ERROR)
        self.message_user(request, f'已拒绝 {len(upload_requests)} 个上传请求。', messages.SUCCESS)


@admin.register(Announcement)
class AnnouncementAdmin(AttachmentReferenceAdminMixin, admin.ModelAdmin):
    list_display = ('content', 'type', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')


@admin.register(Bulletin)
class BulletinsAdmin(AttachmentReferenceAdminMixin, admin.ModelAdmin):
    list_display = ('content', 'title', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')


@admin.register(About)
class AboutAdmin(AttachmentReferenceAdminMixin, admin.ModelAdmin):
    list_display = ('content', 'update_time', 'create_time')
    readonly_fields = ('create_time', 'update_time')
