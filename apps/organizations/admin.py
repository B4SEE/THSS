from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Department, User


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display  = ('name', 'parent_dept', 'description')
    search_fields = ('name',)


@admin.register(User)
class PlatformUserAdmin(BaseUserAdmin):
    list_display  = ('email', 'full_name', 'is_staff', 'is_superuser', 'is_active')
    search_fields = ('email', 'full_name')
    ordering      = ('email',)
    fieldsets = (
        (None,          {'fields': ('email', 'password')}),
        ('Personal',    {'fields': ('full_name',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                    'groups', 'user_permissions')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields':  ('email', 'full_name', 'password1', 'password2'),
        }),
    )

    # Only superadmins can see or touch the Users table
    def has_module_perms(self, request, app_label=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
