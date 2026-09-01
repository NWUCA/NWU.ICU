from django.contrib import admin

from .models import GuestbookEntry, GuestbookLike, GuestbookReport


@admin.register(GuestbookEntry)
class GuestbookEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'author', 'anonymous', 'parent', 'created_at', 'is_deleted', 'like_count')
    list_filter = ('anonymous', 'is_deleted', 'created_at')
    search_fields = ('content', 'author__username', 'author__nickname')
    readonly_fields = ('created_at', 'deleted_at', 'like_count')

    def get_queryset(self, request):
        return GuestbookEntry.all_objects.select_related('author', 'parent')


@admin.register(GuestbookReport)
class GuestbookReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'entry', 'reporter', 'reason', 'status', 'created_at', 'handled_at')
    list_filter = ('reason', 'status', 'created_at')
    search_fields = ('detail', 'handling_note', 'reporter__username')
    readonly_fields = ('created_at',)


@admin.register(GuestbookLike)
class GuestbookLikeAdmin(admin.ModelAdmin):
    list_display = ('entry', 'user', 'created_at')
    readonly_fields = ('created_at',)
