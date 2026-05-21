"""
Interaction logging for the tracking layer.

CampaignTracking — proxy over Campaign used for the admin dashboard sidebar.
Interaction       — immutable record of a single tracking event (open, click, submit, report).
"""
from django.db import models
from django.utils import timezone


from apps.campaigns.models import Campaign


class CampaignTracking(Campaign):
    """Proxy over Campaign — gives the tracking app its own sidebar entry for dashboards."""
    class Meta:
        proxy = True
        verbose_name = 'Campaign Dashboard'
        verbose_name_plural = 'Campaign Dashboards'


class Interaction(models.Model):
    """A single recorded tracking event associated with a CampaignTarget."""

    class EventType(models.TextChoices):
        OPENED        = 'opened',        'Opened'
        CLICKED       = 'clicked',       'Clicked'
        SUBMITTED     = 'submitted',     'Submitted'
        MFA_SUBMITTED = 'mfa_submitted', 'MFA Submitted'
        REPORTED      = 'reported',      'Reported'

    campaign_target = models.ForeignKey(
        'campaigns.CampaignTarget', on_delete=models.CASCADE, related_name='interactions'
    )
    event_type = models.CharField(max_length=15, choices=EventType.choices)
    event_timestamp = models.DateTimeField(default=timezone.now)
    ip_address = models.CharField(max_length=45, blank=True)
    user_agent = models.TextField(blank=True)
    submitted_data = models.JSONField(null=True, blank=True)
    meta           = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'interactions'
        indexes = [
            models.Index(fields=['campaign_target', 'event_type']),
            models.Index(fields=['event_timestamp']),
        ]

    def __str__(self):
        return f'{self.event_type} @ {self.event_timestamp:%Y-%m-%d %H:%M:%S}'
