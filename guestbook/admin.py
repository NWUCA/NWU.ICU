from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied

from .announcements import AnnouncementMustBeHidden, AnnouncementNotFound, delete_announcement
from .models import GuestbookEntry, GuestbookLike, GuestbookReport
from .moderation import resolve_guestbook_report


class GuestbookReportAdminForm(forms.ModelForm):
    class Meta:
        model = GuestbookReport
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk:
            return cleaned
        previous = GuestbookReport.objects.filter(pk=self.instance.pk).values('status').first()
        new_status = cleaned.get('status', self.instance.status)
        if previous and previous['status'] == GuestbookReport.STATUS_PENDING:
            if new_status != GuestbookReport.STATUS_PENDING and not cleaned.get('handling_note', '').strip():
                self.add_error('handling_note', '处理说明不能为空')
        elif previous and new_status != previous['status']:
            self.add_error('status', '已处理举报不能再次改变状态')
        return cleaned


@admin.register(GuestbookEntry)
class GuestbookEntryAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'board', 'author', 'anonymous', 'parent', 'priority', 'is_visible',
        'created_at', 'updated_at', 'is_deleted', 'like_count',
    )
    list_filter = ('board', 'anonymous', 'is_visible', 'is_deleted', 'created_at')
    search_fields = ('title', 'content', 'author__username', 'author__nickname')
    readonly_fields = tuple(field.name for field in GuestbookEntry._meta.fields)
    actions = ['soft_delete_selected']

    @staticmethod
    def has_management_permission(request):
        return (
            request.user.has_perm('guestbook.moderate_reports')
            or request.user.has_perm('guestbook.publish_announcements')
        )

    @staticmethod
    def required_permission_for(entry):
        if entry.board == GuestbookEntry.BOARD_ANNOUNCEMENT and entry.is_root:
            return 'guestbook.publish_announcements'
        return 'guestbook.moderate_reports'

    def has_module_permission(self, request):
        return self.has_management_permission(request)

    def has_view_permission(self, request, obj=None):
        if obj is None:
            return self.has_management_permission(request)
        return request.user.has_perm(self.required_permission_for(obj))

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def get_queryset(self, request):
        queryset = GuestbookEntry.all_objects.select_related('author', 'parent')
        can_moderate = request.user.has_perm('guestbook.moderate_reports')
        can_publish = request.user.has_perm('guestbook.publish_announcements')
        if can_moderate and can_publish:
            return queryset
        announcement_roots = {
            'board': GuestbookEntry.BOARD_ANNOUNCEMENT,
            'parent__isnull': True,
            'root__isnull': True,
        }
        if can_publish:
            return queryset.filter(**announcement_roots)
        if can_moderate:
            return queryset.exclude(**announcement_roots)
        return queryset.none()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='移除选中的内容（保留原文和回复）')
    def soft_delete_selected(self, request, queryset):
        for entry in queryset:
            permission = self.required_permission_for(entry)
            if not request.user.has_perm(permission):
                raise PermissionDenied
            if (
                entry.board == GuestbookEntry.BOARD_ANNOUNCEMENT
                and entry.is_root
                and entry.is_visible
            ):
                self.message_user(request, '请先隐藏公告再删除。', messages.ERROR)
                return
        self.delete_queryset(request, queryset)

    def delete_model(self, request, obj):
        if obj.is_deleted:
            return
        if obj.board == GuestbookEntry.BOARD_ANNOUNCEMENT and obj.is_root:
            try:
                delete_announcement(entry_id=obj.pk)
            except AnnouncementMustBeHidden as error:
                raise PermissionDenied('请先隐藏公告再删除。') from error
            except AnnouncementNotFound:
                return
            return
        obj.soft_delete()

    def delete_queryset(self, request, queryset):
        for entry in queryset.order_by('pk'):
            self.delete_model(request, entry)


@admin.register(GuestbookReport)
class GuestbookReportAdmin(admin.ModelAdmin):
    form = GuestbookReportAdminForm
    list_display = ('id', 'entry', 'reporter', 'reason', 'status', 'created_at', 'handled_at')
    list_filter = ('reason', 'status', 'created_at')
    search_fields = ('detail', 'handling_note', 'reporter__username')
    readonly_fields = ('entry', 'reporter', 'reason', 'detail', 'created_at', 'handled_at', 'handled_by')

    def has_module_permission(self, request):
        return request.user.has_perm('guestbook.moderate_reports')

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('guestbook.moderate_reports')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('guestbook.moderate_reports')

    def get_readonly_fields(self, request, obj=None):
        fields = self.readonly_fields
        if obj is not None and obj.status != GuestbookReport.STATUS_PENDING:
            return fields + ('status', 'handling_note')
        return fields

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = GuestbookReport.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
        if previous_status == GuestbookReport.STATUS_PENDING and obj.status != previous_status:
            resolve_guestbook_report(
                report_id=obj.pk,
                moderator=request.user,
                decision='remove' if obj.status == GuestbookReport.STATUS_REMOVED else 'dismiss',
                note=obj.handling_note,
            )
            obj.refresh_from_db()
            return
        if previous_status != GuestbookReport.STATUS_PENDING:
            obj.refresh_from_db()
            return
        super().save_model(request, obj, form, change)


@admin.register(GuestbookLike)
class GuestbookLikeAdmin(admin.ModelAdmin):
    list_display = ('entry', 'user', 'created_at')
    readonly_fields = ('entry', 'user', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
