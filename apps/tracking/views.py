"""
URL-based tracking endpoints for the phishing simulation.

All endpoints accept a signed token encoding the CampaignTarget pk.
Events are idempotent where appropriate — duplicate clicks are not re-logged,
but duplicate pixel loads always are (email client prefetch compatibility).
"""
import logging
from django.core import signing
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from apps.campaigns.models import CampaignTarget, Campaign
from .models import Interaction
from .tokens import resolve_token

logger = logging.getLogger(__name__)

_PIXEL = bytes([
    0x47,0x49,0x46,0x38,0x39,0x61,0x01,0x00,0x01,0x00,
    0x80,0x00,0x00,0xff,0xff,0xff,0x00,0x00,0x00,0x21,
    0xf9,0x04,0x00,0x00,0x00,0x00,0x00,0x2c,0x00,0x00,
    0x00,0x00,0x01,0x00,0x01,0x00,0x00,0x02,0x02,0x44,
    0x01,0x00,0x3b,
])

_SCANNER_UA = [
    'microsoft url validator',
    'msnbot',
    'bingbot',
    'microsoft-cryptoapi',
    'ms-applinks',
]


def _is_scanner(request) -> bool:
    """Return True if the request User-Agent matches a known security scanner."""
    ua = request.META.get('HTTP_USER_AGENT', '').lower()
    return any(p in ua for p in _SCANNER_UA)


def _parse_ua(ua_string: str) -> dict:
    """Parse a User-Agent string into device, OS, and browser components."""
    ua = (ua_string or '').lower()
    # Device
    device = 'Mobile' if any(h in ua for h in [
        'mobile', 'android', 'iphone', 'ipad', 'ipod', 'windows phone',
    ]) else 'Desktop'
    # OS
    if 'windows nt 10' in ua or 'windows nt 11' in ua:
        os_name = 'Windows 10/11'
    elif 'windows' in ua:
        os_name = 'Windows (older)'
    elif 'iphone' in ua:
        os_name = 'iOS'
    elif 'ipad' in ua:
        os_name = 'iPadOS'
    elif 'mac os x' in ua:
        os_name = 'macOS'
    elif 'android' in ua:
        os_name = 'Android'
    elif 'linux' in ua:
        os_name = 'Linux'
    else:
        os_name = 'Unknown'
    # Browser (order matters: Edge before Chrome, Opera before Chrome)
    if 'edg/' in ua or 'edge/' in ua:
        browser = 'Edge'
    elif 'opr/' in ua or 'opera' in ua:
        browser = 'Opera'
    elif 'chrome/' in ua:
        browser = 'Chrome'
    elif 'firefox/' in ua:
        browser = 'Firefox'
    elif 'safari/' in ua:
        browser = 'Safari'
    elif 'msie' in ua or 'trident/' in ua:
        browser = 'IE'
    else:
        browser = 'Other'
    return {'browser': browser, 'os': os_name, 'device': device}


def _resolve(token: str) -> CampaignTarget:
    """Decode and validate a signed token; raise Http404 on bad signature or missing record."""
    try:
        pk = resolve_token(token)
    except (signing.BadSignature, signing.SignatureExpired):
        raise Http404
    return get_object_or_404(
        CampaignTarget.objects.select_related('campaign__template', 'campaign__sender', 'target'),
        pk=pk,
    )


def _is_finished(ct: CampaignTarget) -> bool:
    """Return True when the campaign is FINISHED or its finish_date has passed."""
    campaign = ct.campaign
    if campaign.status == Campaign.Status.FINISHED:
        return True
    if campaign.finish_date and timezone.now() >= campaign.finish_date:
        return True
    return False


def _get_ip(request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For proxy headers."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def _log(ct: CampaignTarget, event_type: str, request, submitted_data=None):
    """Create an Interaction record for the given event type, enriched with UA and IP metadata."""
    ua_raw = request.META.get('HTTP_USER_AGENT', '')
    meta = {
        'language': request.META.get('HTTP_ACCEPT_LANGUAGE', '')[:80],
        'referer':  request.META.get('HTTP_REFERER', '')[:300],
        **_parse_ua(ua_raw),
    }
    Interaction.objects.create(
        campaign_target=ct,
        event_type=event_type,
        event_timestamp=timezone.now(),
        ip_address=_get_ip(request),
        user_agent=ua_raw[:500],
        submitted_data=submitted_data,
        meta=meta,
    )


def _has_event(ct: CampaignTarget, *event_types) -> bool:
    """Return True if any of the given event_types have been logged for this CampaignTarget."""
    return Interaction.objects.filter(campaign_target=ct, event_type__in=event_types).exists()


def _terminal_redirect(ct: CampaignTarget, name: str, token: str):
    """Return a redirect to the terminal page if a final event was already logged, else None."""
    if _has_event(ct, Interaction.EventType.SUBMITTED, Interaction.EventType.MFA_SUBMITTED):
        return redirect('tracking:feedback', name=name, token=token)
    if _has_event(ct, Interaction.EventType.REPORTED):
        return redirect('tracking:report', name=name, token=token)
    return None


def _capture_js_tracking(post_data: dict) -> dict:
    """Extract JS-injected tracking fields from form POST data."""
    result = {}
    mapping = {
        '_t_time':   'time_on_page_s',
        '_t_scroll': 'scrolled',
        '_t_focus':  'field_focus_count',
        '_t_screen': 'screen_resolution',
    }
    for post_key, out_key in mapping.items():
        val = post_data.get(post_key)
        if val is not None:
            result[out_key] = val
    return result


@require_GET
def pixel(request, name: str, token: str):
    """Serve a 1×1 GIF tracking pixel and log an OPENED event."""
    ct = _resolve(token)
    if not _is_finished(ct):
        _log(ct, Interaction.EventType.OPENED, request)
    return HttpResponse(_PIXEL, content_type='image/gif')


@require_GET
def landing(request, name: str, token: str):
    """Render the phishing landing page and log a CLICKED event on first non-scanner visit."""
    ct = _resolve(token)
    if _is_finished(ct):
        return render(request, 'tracking/campaign_finished.html', {'ct': ct})
    redir = _terminal_redirect(ct, name, token)
    if redir:
        return redir
    if not _has_event(ct, Interaction.EventType.CLICKED) and not _is_scanner(request):
        _log(ct, Interaction.EventType.CLICKED, request)
    category = ct.campaign.template.category
    page = {
        'microsoft365': 'tracking/phishing_microsoft365.html',
        'google':       'tracking/phishing_google.html',
        'ctu':          'tracking/phishing_ctu.html',
    }.get(category, 'tracking/phishing_microsoft365.html')
    return render(request, page, {'ct': ct, 'token': token, 'name': name})


@csrf_exempt
@require_POST
def submit(request, name: str, token: str):
    """Process credential submission; log SUBMITTED event and redirect to MFA or feedback."""
    ct = _resolve(token)
    if _is_finished(ct):
        return render(request, 'tracking/campaign_finished.html', {'ct': ct})
    redir = _terminal_redirect(ct, name, token)
    if redir:
        return redir
    submitted_data = {
        'email': request.POST.get('email', ct.target.email),
        'password_captured': True,
        **_capture_js_tracking(request.POST),
    }
    _log(ct, Interaction.EventType.SUBMITTED, request, submitted_data=submitted_data)
    if ct.campaign.template.category == 'ctu':
        return redirect('tracking:mfa', name=name, token=token)
    return redirect('tracking:feedback', name=name, token=token)


@csrf_exempt
def mfa(request, name: str, token: str):
    """CTU-specific MFA step; log MFA_SUBMITTED on POST and redirect to feedback."""
    ct = _resolve(token)
    if _is_finished(ct):
        return render(request, 'tracking/campaign_finished.html', {'ct': ct})
    if _has_event(ct, Interaction.EventType.MFA_SUBMITTED):
        return redirect('tracking:feedback', name=name, token=token)
    if _has_event(ct, Interaction.EventType.REPORTED):
        return redirect('tracking:report', name=name, token=token)
    if request.method == 'POST':
        submitted_data = {
            'mfa_captured': True,
            **_capture_js_tracking(request.POST),
        }
        _log(ct, Interaction.EventType.MFA_SUBMITTED, request, submitted_data=submitted_data)
        return redirect('tracking:feedback', name=name, token=token)
    approval_number = (abs(hash(token)) % 90) + 10
    return render(request, 'tracking/phishing_ctu_mfa.html', {
        'ct': ct, 'token': token, 'name': name,
        'approval_number': f'{approval_number:02d}',
    })


@require_GET
def feedback(request, name: str, token: str):
    """Render the educational feedback page after a target submits credentials."""
    ct = _resolve(token)
    if _is_finished(ct):
        return render(request, 'tracking/campaign_finished.html', {'ct': ct})
    category = ct.campaign.template.category
    tmpl_name = (
        'tracking/educational_feedback_ctu.html'
        if category == 'ctu'
        else 'tracking/educational_feedback.html'
    )
    return render(request, tmpl_name, {'ct': ct, 'template': ct.campaign.template})


@require_GET
def report(request, name: str, token: str):
    """Render the phishing-reported confirmation page and log a REPORTED event on first visit."""
    ct = _resolve(token)
    if _is_finished(ct):
        return render(request, 'tracking/campaign_finished.html', {'ct': ct})
    if not _has_event(ct, Interaction.EventType.REPORTED):
        if _has_event(ct, Interaction.EventType.SUBMITTED, Interaction.EventType.MFA_SUBMITTED):
            return redirect('tracking:feedback', name=name, token=token)
        if not _is_scanner(request):
            _log(ct, Interaction.EventType.REPORTED, request)
    return render(request, 'tracking/reported.html', {'ct': ct})
