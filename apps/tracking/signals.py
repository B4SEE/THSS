"""
Real-time broadcasting of tracking events via Redis pub/sub.

When an Interaction is created, its metadata is published to the
'dashboard:events' Redis channel for live dashboard updates.
Failures are logged but never re-raised — tracking must not block on Redis.
"""
import json
import logging

import redis
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Interaction

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Interaction)
def broadcast_interaction(sender, instance, created, **kwargs):
    """Publish a newly created Interaction to the Redis dashboard channel."""
    if not created:
        return
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        ct = instance.campaign_target
        payload = json.dumps({
            'event':      'interaction',
            'id':         instance.id,
            'event_type': instance.event_type,
            'timestamp':  instance.event_timestamp.isoformat(),
            'campaign':   ct.campaign.name,
            'user_email': ct.target.email,
            'user_name':  ct.target.full_name,
            'ip_address': instance.ip_address,
        })
        r.publish('dashboard:events', payload)
    except Exception:
        logger.exception('Failed to broadcast interaction #%s', instance.id)
