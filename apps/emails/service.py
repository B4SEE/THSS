"""
Outbound phishing email delivery via the Resend API.

Tracking tokens and convincing URL spoofing are injected here.
The @ trick (https://prefix@real-host) makes links appear to come from
a legitimate domain in plain-text email clients.
"""
import logging
import re
from datetime import timedelta
from urllib.parse import urlparse

import resend
from django.conf import settings
from django.utils import timezone

from apps.campaigns.models import CampaignTarget
from apps.tracking.tokens import make_token

logger = logging.getLogger(__name__)

_CATEGORY_PREFIX = {
    'microsoft365': 'microsoft.security',
    'google':       'google.security',
    'ctu':          'login.cvut.cz',
}

def _name_slug(full_name: str) -> str:
    """Convert a full name to a URL-safe dot-separated slug (e.g. 'John Doe' → 'john.doe')."""
    slug = re.sub(r'[^a-z0-9]+', '.', full_name.lower()).strip('.')
    return slug or 'user'


def _convincing_base(base: str, category: str) -> str:
    """Return base URL with @ trick: https://prefix@host so links look like email addresses."""
    parsed = urlparse(base)
    prefix = _CATEGORY_PREFIX.get(category, 'it.security')
    return f'{parsed.scheme}://{prefix}@{parsed.netloc}'


class PhishingEmailService:
    """
    Sends a single phishing email for a CampaignTarget via Resend.

    Applies A/B overrides (template / subject / sender) when the target's variant
    differs from the control group, then renders the template and dispatches via Resend.
    """

    def send_for_target(self, ct: CampaignTarget) -> bool:
        """
        Build and send the phishing email for the given CampaignTarget.

        Returns True on success, False on any Resend API failure.
        """
        resend.api_key = settings.RESEND_API_KEY

        token    = make_token(ct.id)
        base     = settings.PLATFORM_BASE_URL.rstrip('/')
        name     = _name_slug(ct.target.full_name)
        category = ct.campaign.template.category

        link_base = _convincing_base(base, category)
        d = timezone.now() + timedelta(days=7)
        urls = {
            'click_url':  f'{link_base}/t/{name}/{token}/',
            'report_url': f'{link_base}/t/{name}/{token}/report/',
            'pixel_url':  f'{base}/t/{name}/{token}/logo.gif',
        }
        context = {
            'first_name': ct.target.full_name.split()[0],
            'full_name':  ct.target.full_name,
            'deadline':   f'{d.day}.&nbsp;{d.month}.&nbsp;{d.year}',
            **urls,
        }

        ab = (ct.campaign.ab_tests.select_related('template', 'sender')
              .filter(variant_name=ct.variant).first()
              if ct.variant and ct.variant != 'A' else None)
        template  = (ab.template if ab else None) or ct.campaign.template
        subject   = (ab.subject_override if ab and ab.subject_override else None) or template.subject
        html_body = self._render(template.body, context)
        html_body += (
            f'<img src="{urls["pixel_url"]}" width="1" height="1" '
            f'alt="" style="display:none;visibility:hidden"/>'
        )
        text_body = f'Please visit: {urls["click_url"]}\n\nReport phishing: {urls["report_url"]}'

        sender     = (ab.sender if ab and ab.sender else None) or ct.campaign.sender
        from_email = sender.formatted if sender else settings.DEFAULT_FROM_EMAIL
        params: resend.Emails.SendParams = {
            'from':    from_email,
            'to':      [ct.target.email],
            'subject': subject,
            'html':    html_body,
            'text':    text_body,
        }
        if sender and sender.reply_to:
            params['reply_to'] = sender.reply_to

        try:
            result = resend.Emails.send(params)
            logger.info('Sent to %s (ct=%s resend_id=%s)', ct.target.email, ct.id, result.get('id'))
            return True
        except Exception:
            logger.exception('Failed to send to %s (ct=%s)', ct.target.email, ct.id)
            return False

    @staticmethod
    def _render(body: str, context: dict) -> str:
        """Replace {{key}} placeholders in body with their string values from context."""
        for key, value in context.items():
            body = body.replace('{{' + key + '}}', str(value))
        return body
