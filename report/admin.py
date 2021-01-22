from django.contrib import admin

from report.models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'last_report_message')
    list_filter = (
        'status',
        ('last_report_message', admin.EmptyFieldListFilter),
    )
    search_fields = ('user__username',)
