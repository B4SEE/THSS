import logging
import threading
import time

logger = logging.getLogger(__name__)
_started = False


def _run():
    from django.utils import timezone
    from apps.campaigns.models import Campaign
    from apps.campaigns.service import CampaignService

    while True:
        try:
            due = Campaign.objects.filter(
                status=Campaign.Status.SCHEDULED,
                approved_by__isnull=False,
                scheduled_date__lte=timezone.now(),
            )
            for campaign in due:
                logger.info('Scheduler: auto-sending campaign "%s"', campaign.name)
                CampaignService().send(campaign)
        except Exception:
            logger.exception('Campaign scheduler error')
        time.sleep(60)


def start_scheduler():
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_run, daemon=True, name='campaign-scheduler')
    t.start()
    logger.info('Campaign scheduler started')
