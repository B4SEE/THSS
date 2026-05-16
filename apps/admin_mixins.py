from django.contrib import admin


def _get_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def audit(request, action, obj=None, changes=None, entity_type=None, entity_id=None):
    from apps.audit.models import AuditLog
    user = getattr(request, 'user', None)
    authenticated = user is not None and getattr(user, 'is_authenticated', False)
    AuditLog.objects.create(
        user         = user if authenticated else None,
        actor_email  = user.email if authenticated else '',
        actor_name   = user.full_name if authenticated else '',
        ip_address   = _get_ip(request) if request else None,
        action       = action,
        entity_type  = entity_type or (obj.__class__.__name__ if obj else ''),
        entity_id    = entity_id or (obj.pk if obj else None),
        changes      = changes,
    )


class StaffAccessMixin:
    """Grant any is_staff user full CRUD access. Action-level superuser gates stay in place."""

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request, obj=None):
        return request.user.is_staff

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def has_delete_permission(self, request, obj=None):
        return request.user.is_staff


class StaffViewOnlyMixin:
    """Grant any is_staff user read-only access (no add / change / delete)."""

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
