from django.contrib import admin

from report.models import Report


@admin.register(Report)
class UserAdmin(admin.ModelAdmin):
    list_display = ('user', 'status')
    list_filter = ('status',)
    search_fields = ('user__username',)
