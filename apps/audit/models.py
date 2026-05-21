"""
Immutable audit trail for all admin actions on the platform.

AuditLog entries are created by the audit() helper in admin_mixins.py
and by the auth signal handlers in audit/apps.py.  Entries are never updated.
"""
from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """
    Append-only record of an admin action.

    Actor identity is denormalized (actor_email, actor_name) so entries survive
    user deletion.  The FK user field is nullable for the same reason.
    """
    timestamp    = models.DateTimeField(auto_now_add=True, db_index=True)

    # Who did it — FK may be null if user deleted; email/name preserved in denorm fields
    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='audit_logs'
    )
    actor_email  = models.CharField(max_length=254, blank=True)
    actor_name   = models.CharField(max_length=255, blank=True)
    ip_address   = models.GenericIPAddressField(null=True, blank=True)

    # What happened
    action       = models.CharField(max_length=100, db_index=True)

    # What it happened to
    entity_type  = models.CharField(max_length=100, blank=True)
    entity_id    = models.IntegerField(null=True, blank=True)

    # Structured details — snapshots, diffs, etc.
    changes      = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']

    def __str__(self):
        actor = self.actor_email or '(unknown)'
        return f'[{self.timestamp:%Y-%m-%d %H:%M}] {actor} — {self.action}'
