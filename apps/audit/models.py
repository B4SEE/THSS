from django.db import models
from django.conf import settings


class AuditLog(models.Model):
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
