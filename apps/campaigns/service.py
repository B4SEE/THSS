"""Business logic for sending campaigns and managing their lifecycle."""
import logging
import random
import time

from django.conf import settings
from django.utils import timezone

from apps.campaigns.models import Campaign, CampaignTarget

logger = logging.getLogger(__name__)


class CampaignService:
    """
    Orchestrates campaign dispatch.

    send()                — resolve recipients, allocate variants, fire emails.
    reset()               — roll back a campaign to Draft.
    _resolve_recipients() — apply targeting mode and exclusion rules.
    _build_variant_map()  — proportionally assign A/B variants.
    """

    def send(self, campaign: Campaign, batch_limit: int = 0, send_delay: float | None = None):
        """
        Send phishing emails for a campaign.
        Returns (sent, failed, skipped, remaining).
          batch_limit — stop after N sends (0 = unlimited).
          send_delay  — seconds between sends (default: settings.EMAIL_SEND_DELAY).
        """
        from apps.emails.service import PhishingEmailService

        delay = send_delay if send_delay is not None else settings.EMAIL_SEND_DELAY
        limit = batch_limit if batch_limit else settings.EMAIL_BATCH_SIZE

        recipients = self._resolve_recipients(campaign)
        if not recipients:
            return 0, 0, 0, 0

        variant_map = self._build_variant_map(campaign, recipients)

        campaign.status = Campaign.Status.RUNNING
        campaign.save(update_fields=['status', 'updated_at'])

        email_svc = PhishingEmailService()
        sent = failed = skipped = 0

        for target in recipients:
            assigned = variant_map.get(target.pk, 'A') if variant_map else ''
            ct, created = CampaignTarget.objects.get_or_create(
                campaign=campaign,
                target=target,
                defaults={'variant': assigned},
            )
            if not created and ct.variant != assigned and ct.sent_at is None:
                ct.variant = assigned
                ct.save(update_fields=['variant'])

            if ct.sent_at:
                skipped += 1
                continue

            if limit and sent >= limit:
                break

            ok = email_svc.send_for_target(ct)
            if ok:
                ct.sent_at = timezone.now()
                ct.save(update_fields=['sent_at'])
                sent += 1
                if delay > 0:
                    time.sleep(delay)
            else:
                failed += 1

        remaining = campaign.targets.filter(sent_at__isnull=True).count()
        existing_ids = set(campaign.targets.values_list('target_id', flat=True))
        remaining += sum(1 for t in recipients if t.pk not in existing_ids)

        campaign.status = Campaign.Status.COMPLETED if remaining == 0 else Campaign.Status.RUNNING
        campaign.save(update_fields=['status', 'updated_at'])

        logger.info('Campaign "%s": sent=%s failed=%s skipped=%s remaining=%s',
                    campaign.name, sent, failed, skipped, remaining)
        return sent, failed, skipped, remaining

    @staticmethod
    def _build_variant_map(campaign: Campaign, recipients: list) -> dict:
        """Return {target_pk: variant_name}. Assigns variants proportionally from ABTest config."""
        ab_tests = list(campaign.ab_tests.all())
        if not ab_tests:
            return {}

        shuffled = list(recipients)
        random.shuffle(shuffled)
        total = len(shuffled)

        ab_total_pct = sum(ab.allocation_percentage for ab in ab_tests)
        control_pct = max(0, 100 - ab_total_pct)

        slots = []
        slots.extend(['A'] * round(total * control_pct / 100))
        for ab in ab_tests:
            slots.extend([ab.variant_name] * round(total * ab.allocation_percentage / 100))
        while len(slots) < total:
            slots.append('A')
        slots = slots[:total]

        return {r.pk: slots[i] for i, r in enumerate(shuffled)}

    @staticmethod
    def reset(campaign: Campaign):
        """Reset campaign to Draft; clear all sent_at timestamps and remove approver."""
        campaign.targets.all().update(sent_at=None)
        campaign.status = Campaign.Status.DRAFT
        campaign.approved_by = None
        campaign.save(update_fields=['status', 'approved_by', 'updated_at'])

    @staticmethod
    def _resolve_recipients(campaign: Campaign) -> list:
        """
        Return the final list of opt-in Targets for this campaign.

        Applies the campaign's targeting mode (ALL / DEPARTMENT / GROUP / INDIVIDUAL),
        merges individual_targets add-ons, then strips excluded_targets and opted-out targets.
        """
        from apps.targets.models import Target
        base = Target.objects.filter(opt_out=False)

        if campaign.target_type == Campaign.TargetType.ALL:
            recipients = list(base)
        elif campaign.target_type == Campaign.TargetType.DEPARTMENT:
            dept_ids = list(campaign.target_departments.values_list('pk', flat=True))
            if not dept_ids:
                raise ValueError('Campaign has no target departments set')
            recipients = list(base.filter(department__in=dept_ids).distinct())
            seen = {t.pk for t in recipients}
            for t in campaign.individual_targets.filter(opt_out=False):
                if t.pk not in seen:
                    recipients.append(t)
        elif campaign.target_type == Campaign.TargetType.GROUP:
            group_ids = list(campaign.target_groups.values_list('pk', flat=True))
            if not group_ids:
                raise ValueError('Campaign has no target groups set')
            recipients = list(base.filter(groups__in=group_ids).distinct())
            seen = {t.pk for t in recipients}
            for t in campaign.individual_targets.filter(opt_out=False):
                if t.pk not in seen:
                    recipients.append(t)
        elif campaign.target_type == Campaign.TargetType.INDIVIDUAL:
            recipients = list(campaign.individual_targets.filter(opt_out=False))
        else:
            recipients = []

        excluded_ids = set(campaign.excluded_targets.values_list('pk', flat=True))
        if excluded_ids:
            recipients = [t for t in recipients if t.pk not in excluded_ids]
        return recipients
