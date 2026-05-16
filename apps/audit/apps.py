from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.audit'
    label = 'audit'

    def ready(self):
        from django.contrib.auth.signals import (
            user_logged_in, user_logged_out, user_login_failed,
        )
        user_logged_in.connect(_on_login)
        user_logged_out.connect(_on_logout)
        user_login_failed.connect(_on_login_failed)


def _get_ip(request):
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def _on_login(sender, request, user, **kwargs):
    from apps.audit.models import AuditLog
    AuditLog.objects.create(
        user        = user,
        actor_email = user.email,
        actor_name  = user.full_name,
        ip_address  = _get_ip(request),
        action      = 'login',
        entity_type = 'User',
        entity_id   = user.pk,
    )


def _on_logout(sender, request, user, **kwargs):
    from apps.audit.models import AuditLog
    if not user:
        return
    AuditLog.objects.create(
        user        = user,
        actor_email = user.email,
        actor_name  = user.full_name,
        ip_address  = _get_ip(request),
        action      = 'logout',
        entity_type = 'User',
        entity_id   = user.pk,
    )


def _on_login_failed(sender, credentials, request, **kwargs):
    from apps.audit.models import AuditLog
    attempted_email = credentials.get('username', '') or credentials.get('email', '')
    AuditLog.objects.create(
        actor_email = attempted_email,
        ip_address  = _get_ip(request),
        action      = 'login_failed',
        entity_type = 'User',
        changes     = {'attempted_email': attempted_email},
    )
