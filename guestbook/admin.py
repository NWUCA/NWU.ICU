from django.contrib import admin
from django.utils import timezone

from .models import GuestbookEntry, GuestbookLike, GuestbookReport
from .notifications import notify_guestbook_report


@admin.register(GuestbookEntry)
class GuestbookEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'board', 'author', 'anonymous', 'parent', 'created_at', 'is_deleted', 'like_count')
    list_filter = ('board', 'anonymous', 'is_deleted', 'created_at')
    search_fields = ('title', 'content', 'author__username', 'author__nickname')
    readonly_fields = tuple(field.name for field in GuestbookEntry._meta.fields)
    actions = ['soft_delete_selected']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='移除选中的内容（保留原文和回复）')
    def soft_delete_selected(self, request, queryset):
        self.delete_queryset(request, queryset)

    def delete_model(self, request, obj):
        obj.soft_delete()

    def delete_queryset(self, request, queryset):
        for entry in queryset.order_by('pk'):
            entry.soft_delete()

    def get_queryset(self, request):
        return GuestbookEntry.all_objects.select_related('author', 'parent')


@admin.register(GuestbookReport)
class GuestbookReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'entry', 'reporter', 'reason', 'status', 'created_at', 'handled_at')
    list_filter = ('reason', 'status', 'created_at')
    search_fields = ('detail', 'handling_note', 'reporter__username')
    readonly_fields = ('entry', 'reporter', 'reason', 'detail', 'created_at', 'handled_at', 'handled_by')

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = GuestbookReport.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
        if obj.status != GuestbookReport.STATUS_PENDING:
            obj.handled_by = request.user
            obj.handled_at = timezone.now()
        super().save_model(request, obj, form, change)
        if obj.status == GuestbookReport.STATUS_REMOVED and not obj.entry.is_deleted:
            obj.entry.soft_delete()
        if obj.status != GuestbookReport.STATUS_PENDING and obj.status != previous_status:
            notify_guestbook_report(obj)


@admin.register(GuestbookLike)
class GuestbookLikeAdmin(admin.ModelAdmin):
    list_display = ('entry', 'user', 'created_at')
    readonly_fields = ('entry', 'user', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
