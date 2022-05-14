from django.contrib import admin

from user.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    search_fields = ('username', 'name')
    list_display = ('username', 'name', 'nickname')
    list_filter = (('nickname', admin.EmptyFieldListFilter),)
    fields = (
        'username',
        'nickname',
        'last_login',
        'is_superuser',
        'is_staff',
        'name',
        'cookie_last_update',
    )
