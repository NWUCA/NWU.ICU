from django.contrib import admin

from .models import Announcement, Bulletins


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('content', 'type', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')


@admin.register(Bulletins)
class BulletinsAdmin(admin.ModelAdmin):
    list_display = ('content', 'title', 'update_time', 'enabled')
    list_filter = ('enabled',)
    readonly_fields = ('create_time', 'update_time')
