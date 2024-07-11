from django.contrib import admin

from .models import Announcement, Bulletin, About


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
