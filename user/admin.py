from django.contrib import admin

from user.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    search_fields = ('username',)
    list_display = ('username', 'name')
    fields = ('username', 'last_login', 'is_superuser', 'is_staff', 'name', 'cookie_last_update')
