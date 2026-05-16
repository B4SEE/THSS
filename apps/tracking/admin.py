import json
import zoneinfo
from collections import Counter, defaultdict

from django.contrib import admin
from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from apps.admin_mixins import StaffAccessMixin
from .models import Interaction, CampaignTracking

_LOCAL_TZ = zoneinfo.ZoneInfo(settings.TIME_ZONE)

_SCANNER_UA = [
    'microsoft url validator',
    'msnbot',
    'bingbot',
    'microsoft-cryptoapi',
    'ms-applinks',
]


def _is_scanner_ua(interaction):
    ua = (interaction.user_agent or '').lower()
    return any(p in ua for p in _SCANNER_UA)


# ── Base helpers ──────────────────────────────────────────────────────────────

def _load_campaign(object_id):
    from apps.campaigns.models import Campaign
    return Campaign.objects.select_related(
        'template', 'sender', 'approved_by', 'created_by'
    ).get(pk=object_id)


def _sent_count(campaign):
    from apps.campaigns.models import CampaignTarget
    return CampaignTarget.objects.filter(campaign=campaign, sent_at__isnull=False).count()


def _first_sent(campaign):
    from apps.campaigns.models import CampaignTarget
    return (CampaignTarget.objects
            .filter(campaign=campaign, sent_at__isnull=False)
            .order_by('sent_at')
            .values_list('sent_at', flat=True)
            .first())


def _event_counts(campaign):
    rows = (Interaction.objects
            .filter(campaign_target__campaign=campaign)
            .values('event_type')
            .annotate(n=Count('id')))
    return {r['event_type']: r['n'] for r in rows}


def _enrich(interactions, campaign):
    from apps.campaigns.models import CampaignTarget
    sent_map = {
        ct.target_id: ct.sent_at
        for ct in CampaignTarget.objects.filter(campaign=campaign).only('target_id', 'sent_at')
    }
    open_map = {}
    for i in interactions:
        if i.event_type == Interaction.EventType.OPENED:
            open_map[i.campaign_target_id] = i.event_timestamp

    result = []
    for i in interactions:
        delta_seconds = delta_source = None
        if i.event_type != Interaction.EventType.OPENED:
            base = open_map.get(i.campaign_target_id)
            src = 'open'
            if not base:
                base = sent_map.get(i.campaign_target.target_id)
                src = 'send'
            if base:
                d = int((i.event_timestamp - base).total_seconds())
                if d >= 0:
                    delta_seconds, delta_source = d, src
        i.delta_seconds = delta_seconds
        i.delta_source = delta_source
        if delta_seconds is not None:
            i.delta_minutes = delta_seconds // 60
            i.delta_remainder = delta_seconds % 60
        result.append(i)
    return result


def _funnel(counts, sent):
    rows = []
    for label, key in [
        ('Sent', None), ('Opened', 'opened'), ('Clicked', 'clicked'),
        ('Submitted', 'submitted'), ('MFA Submitted', 'mfa_submitted'), ('Reported', 'reported'),
    ]:
        n = sent if key is None else counts.get(key, 0)
        pct = round(n / sent * 100, 1) if sent else 0
        rows.append({'label': label, 'n': n, 'pct': pct})
    return rows


def _build_timeline_json(interactions):
    days = defaultdict(lambda: defaultdict(int))
    for i in interactions:
        day = i.event_timestamp.astimezone(_LOCAL_TZ).strftime('%Y-%m-%d')
        days[day][i.event_type] += 1
    sorted_days = sorted(days)
    return json.dumps({
        'days':          sorted_days,
        'opened':        [days[d].get('opened', 0) for d in sorted_days],
        'clicked':       [days[d].get('clicked', 0) for d in sorted_days],
        'submitted':     [days[d].get('submitted', 0) for d in sorted_days],
        'mfa_submitted': [days[d].get('mfa_submitted', 0) for d in sorted_days],
        'reported':      [days[d].get('reported', 0) for d in sorted_days],
    })


# ── Analytics helpers ─────────────────────────────────────────────────────────

def _dept_breakdown(cts, raw_interactions):
    """Click/submit/report counts per department, sorted by click rate desc."""
    dept_sent = defaultdict(int)
    ct_to_dept = {}
    for ct in cts:
        dept = ct.target.department.name if ct.target.department_id else 'No department'
        ct_to_dept[ct.id] = dept
        dept_sent[dept] += 1

    dept_ev = defaultdict(lambda: defaultdict(int))
    for i in raw_interactions:
        dept = ct_to_dept.get(i.campaign_target_id)
        if dept:
            dept_ev[dept][i.event_type] += 1

    result = []
    for dept, sent_n in dept_sent.items():
        ev = dept_ev.get(dept, {})
        clicked = ev.get('clicked', 0)
        result.append({
            'dept':      dept,
            'sent':      sent_n,
            'clicked':   clicked,
            'submitted': ev.get('submitted', 0) + ev.get('mfa_submitted', 0),
            'reported':  ev.get('reported', 0),
            'click_pct': round(clicked / sent_n * 100, 1) if sent_n else 0.0,
        })
    result.sort(key=lambda x: x['click_pct'], reverse=True)
    return result


def _time_to_click_dist(cts, raw_interactions):
    """Histogram of time from send to first click, in six buckets."""
    sent_map = {ct.target_id: ct.sent_at for ct in cts}

    BUCKETS = [
        ('<1 min',     60),
        ('1–5 min',    300),
        ('5–30 min',   1800),
        ('30 min–2 h', 7200),
        ('2–24 h',     86400),
        ('>24 h',      None),
    ]
    counts = {label: 0 for label, _ in BUCKETS}

    for i in raw_interactions:
        if i.event_type != 'clicked':
            continue
        baseline = sent_map.get(i.campaign_target.target_id)
        if not baseline:
            continue
        delta = (i.event_timestamp - baseline).total_seconds()
        if delta < 0:
            continue
        for label, limit in BUCKETS:
            if limit is None or delta < limit:
                counts[label] += 1
                break

    return {
        'labels': [b[0] for b in BUCKETS],
        'data':   [counts[b[0]] for b in BUCKETS],
    }


def _email_providers(cts):
    """Breakdown of target email providers (domains)."""
    counter = Counter(
        ct.target.email.split('@')[1].lower()
        for ct in cts
        if ct.target.email and '@' in ct.target.email
    )
    top = counter.most_common(7)
    other = sum(counter.values()) - sum(n for _, n in top)
    labels = [d for d, _ in top]
    data   = [n for _, n in top]
    if other > 0:
        labels.append('other')
        data.append(other)
    return {'labels': labels, 'data': data}


def _risky_users_campaign(cts, raw_interactions):
    """Users who clicked or submitted in this campaign."""
    ct_map = {ct.id: ct for ct in cts}
    user_ev = {}

    for i in raw_interactions:
        ct = ct_map.get(i.campaign_target_id)
        if not ct:
            continue
        tid = ct.target_id
        if tid not in user_ev:
            user_ev[tid] = {
                'name':      ct.target.full_name,
                'email':     ct.target.email,
                'dept':      ct.target.department.name if ct.target.department_id else '—',
                'clicked':   False,
                'submitted': False,
                'reported':  False,
            }
        if i.event_type == 'clicked':
            user_ev[tid]['clicked'] = True
        elif i.event_type in ('submitted', 'mfa_submitted'):
            user_ev[tid]['submitted'] = True
        elif i.event_type == 'reported':
            user_ev[tid]['reported'] = True

    risky = [u for u in user_ev.values() if u['clicked'] or u['submitted']]
    risky.sort(key=lambda u: (u['submitted'], u['clicked']), reverse=True)
    return risky[:20]


def _repeat_offenders():
    """Users ranked by credential submissions across all campaigns."""
    rows = (
        Interaction.objects
        .filter(event_type__in=['submitted', 'mfa_submitted'])
        .values(
            'campaign_target__target_id',
            'campaign_target__target__full_name',
            'campaign_target__target__email',
            'campaign_target__target__department__name',
        )
        .annotate(
            submit_count=Count('id'),
            campaign_count=Count('campaign_target__campaign_id', distinct=True),
        )
        .order_by('-campaign_count', '-submit_count')[:10]
    )
    return [
        {
            'name':      r['campaign_target__target__full_name'],
            'email':     r['campaign_target__target__email'],
            'dept':      r['campaign_target__target__department__name'] or '—',
            'submits':   r['submit_count'],
            'campaigns': r['campaign_count'],
        }
        for r in rows
    ]


def _ignored_count(cts, raw_interactions):
    """Count of sent targets that had zero interactions."""
    ct_ids_with_events = {i.campaign_target_id for i in raw_interactions}
    return sum(1 for ct in cts if ct.id not in ct_ids_with_events)


def _hourly_heatmap(raw_interactions):
    """7×24 matrix of click/submit events by day-of-week (0=Mon) × hour."""
    matrix = [[0] * 24 for _ in range(7)]
    for i in raw_interactions:
        if i.event_type not in ('clicked', 'submitted', 'mfa_submitted'):
            continue
        local_dt = i.event_timestamp.astimezone(_LOCAL_TZ)
        matrix[local_dt.weekday()][local_dt.hour] += 1
    return matrix


def _cumulative_engagement(cts, raw_interactions):
    """Cumulative % of targets who engaged (clicked/submitted) over hours since first send."""
    sent_times = [ct.sent_at for ct in cts if ct.sent_at]
    if not sent_times:
        return {'hours': [], 'pct': []}
    t0 = min(sent_times)
    total = len(cts)
    first_engage = {}
    for i in raw_interactions:
        if i.event_type not in ('clicked', 'submitted', 'mfa_submitted'):
            continue
        ct_id = i.campaign_target_id
        if ct_id not in first_engage or i.event_timestamp < first_engage[ct_id]:
            first_engage[ct_id] = i.event_timestamp
    if not first_engage:
        return {'hours': [], 'pct': []}
    deltas = sorted(
        (t - t0).total_seconds() / 3600
        for t in first_engage.values()
        if t >= t0
    )
    max_h = deltas[-1] if deltas else 0
    step = max(0.5, round(max_h / 40, 1))
    pts = []
    h = 0.0
    while h <= max_h + step:
        count = sum(1 for d in deltas if d <= h)
        pts.append({'h': round(h, 1), 'pct': round(count / total * 100, 1)})
        h += step
    return {'hours': [p['h'] for p in pts], 'pct': [p['pct'] for p in pts]}


def _device_os_breakdown(raw_interactions):
    """Counts from meta.device/os/browser for click/submit events."""
    device_c, os_c, browser_c = Counter(), Counter(), Counter()
    for i in raw_interactions:
        if i.event_type not in ('clicked', 'submitted', 'mfa_submitted'):
            continue
        meta = i.meta or {}
        if meta.get('device'):
            device_c[meta['device']] += 1
        if meta.get('os'):
            os_c[meta['os']] += 1
        if meta.get('browser'):
            browser_c[meta['browser']] += 1
    return {
        'device':  {'labels': list(device_c.keys()),  'data': list(device_c.values())},
        'os':      {'labels': list(os_c.keys()),       'data': list(os_c.values())},
        'browser': {'labels': list(browser_c.keys()),  'data': list(browser_c.values())},
    }


def _ab_comparison(cts, raw_interactions):
    """Per-variant click/submit/report rates. Returns None if no variants defined."""
    variant_map = {ct.id: ct.variant for ct in cts if ct.variant}
    if not variant_map:
        return None
    sent = defaultdict(int)
    ev   = defaultdict(lambda: defaultdict(int))
    for ct in cts:
        if ct.variant:
            sent[ct.variant] += 1
    for i in raw_interactions:
        v = variant_map.get(i.campaign_target_id)
        if v:
            ev[v][i.event_type] += 1
    result = []
    for variant, sent_n in sorted(sent.items()):
        e = ev.get(variant, {})
        clicked   = e.get('clicked', 0)
        submitted = e.get('submitted', 0) + e.get('mfa_submitted', 0)
        reported  = e.get('reported', 0)
        result.append({
            'variant':   variant,
            'sent':      sent_n,
            'click_pct': round(clicked   / sent_n * 100, 1) if sent_n else 0,
            'sub_pct':   round(submitted / sent_n * 100, 1) if sent_n else 0,
            'rep_pct':   round(reported  / sent_n * 100, 1) if sent_n else 0,
        })
    return result


def _click_to_submit_delta(raw_interactions):
    """Histogram of seconds between first click and submit per target."""
    BUCKETS = [
        ('<30 s',   30),
        ('30s–2m',  120),
        ('2–5 min', 300),
        ('5–15 min',900),
        ('15–60m',  3600),
        ('>1 h',    None),
    ]
    click_times = {}
    for i in raw_interactions:
        if i.event_type == 'clicked':
            ct_id = i.campaign_target_id
            if ct_id not in click_times or i.event_timestamp < click_times[ct_id]:
                click_times[ct_id] = i.event_timestamp
    bucket_counts = {label: 0 for label, _ in BUCKETS}
    for i in raw_interactions:
        if i.event_type not in ('submitted', 'mfa_submitted'):
            continue
        click_t = click_times.get(i.campaign_target_id)
        if not click_t:
            continue
        delta = (i.event_timestamp - click_t).total_seconds()
        if delta < 0:
            continue
        for label, limit in BUCKETS:
            if limit is None or delta < limit:
                bucket_counts[label] += 1
                break
    return {'labels': [b[0] for b in BUCKETS], 'data': [bucket_counts[b[0]] for b in BUCKETS]}


def _chart_callouts(counts, sent, dept_data, ttc_data, heatmap, cum_data, device_os, cts2_data):
    """Returns dict of per-chart callout strings."""
    callouts = {}
    clicked   = counts.get('clicked', 0)
    submitted = counts.get('submitted', 0) + counts.get('mfa_submitted', 0)

    # Department
    if dept_data and dept_data[0]['click_pct'] > 0:
        worst = dept_data[0]
        best  = dept_data[-1]
        txt = f'{worst["dept"]} had the highest click rate at {worst["click_pct"]}%.'
        if best['click_pct'] == 0:
            txt += f' {best["dept"]} had no clicks.'
        elif best['click_pct'] < worst['click_pct']:
            txt += f' {best["dept"]} had the lowest at {best["click_pct"]}%.'
        callouts['dept'] = txt
    elif dept_data:
        callouts['dept'] = 'No clicks recorded in any department.'

    # Time-to-click
    if ttc_data and any(ttc_data.get('data', [])):
        data = ttc_data['data']
        total = sum(data)
        if total:
            fast = data[0] + (data[1] if len(data) > 1 else 0)  # <1m + 1-5m
            callouts['ttc'] = f'{round(fast/total*100)}% of clicks happened within 5 min of delivery.'

    # Heatmap
    if heatmap:
        DAY = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
        best_val, best_dow, best_h = 0, 0, 0
        for dow, row in enumerate(heatmap):
            for hour, val in enumerate(row):
                if val > best_val:
                    best_val, best_dow, best_h = val, dow, hour
        if best_val > 0:
            callouts['heatmap'] = (
                f'Peak: {DAY[best_dow]} {best_h:02d}:00 — '
                f'{best_val} event{"s" if best_val != 1 else ""}.'
            )

    # Cumulative
    if cum_data and cum_data.get('pct'):
        pcts  = cum_data['pct']
        hours = cum_data['hours']
        final = pcts[-1]
        half_idx = next((i for i, p in enumerate(pcts) if p >= final / 2), None)
        if half_idx is not None and hours:
            callouts['cumulative'] = (
                f'{final}% of targets engaged. '
                f'50% of all responses came within {hours[half_idx]:.0f}h of sending.'
            )

    # Device
    dv = device_os.get('device', {})
    if dv.get('data') and sum(dv['data']):
        total = sum(dv['data'])
        labels = dv['labels']
        data   = dv['data']
        mob_idx = next((i for i, l in enumerate(labels) if 'mobile' in l.lower()), None)
        if mob_idx is not None:
            callouts['device'] = f'{round(data[mob_idx]/total*100)}% of interactions came from mobile.'
        else:
            callouts['device'] = 'All recorded interactions came from desktop devices.'

    # Click-to-submit
    if cts2_data and any(cts2_data.get('data', [])):
        data = cts2_data['data']
        total = sum(data)
        if total and submitted:
            fast = data[0] + (data[1] if len(data) > 1 else 0)  # <30s + 30s-2m
            callouts['cts2'] = (
                f'{round(fast/total*100)}% of submitters entered credentials within 2 min of clicking.'
            )

    return callouts


def _generate_report_insights(counts, sent, dept_data, ttc_data,
                              cum_data=None, cts2_data=None, device_os=None, ab_data=None):
    """Return list of human-readable insight strings derived from campaign data."""
    if not sent:
        return ['No emails were sent in this campaign.']

    insights = []
    clicked   = counts.get('clicked', 0)
    submitted = counts.get('submitted', 0) + counts.get('mfa_submitted', 0)
    reported  = counts.get('reported', 0)
    opened    = counts.get('opened', 0)

    click_pct = round(clicked / sent * 100, 1) if sent else 0
    # Industry benchmark note
    insights.append(
        'Industry benchmark: phishing simulation click rates typically range from 15–30% '
        'for untrained populations (Proofpoint 2023 State of the Phish).'
    )

    if clicked:
        insights.append(
            f'{clicked} of {sent} recipients ({click_pct}%) clicked the phishing link.'
        )
    else:
        insights.append(f'None of the {sent} recipients clicked the link.')

    if submitted:
        sub_pct = round(submitted / sent * 100, 1)
        s = 's' if submitted != 1 else ''
        insights.append(
            f'{submitted} recipient{s} ({sub_pct}%) submitted credentials on the phishing page.'
        )

    if reported:
        rep_pct = round(reported / sent * 100, 1)
        s = 's' if reported != 1 else ''
        insights.append(
            f'{reported} recipient{s} ({rep_pct}%) identified and reported the simulation.'
        )

    if opened > 0 and clicked == 0:
        insights.append(
            f'{opened} recipients opened the email but none followed the link — '
            'awareness may be developing.'
        )

    if clicked > 0 and submitted > 0:
        conv = round(submitted / clicked * 100, 1)
        insights.append(
            f'Of those who clicked, {conv}% proceeded to enter credentials.'
        )

    if dept_data:
        worst = dept_data[0]
        if worst['click_pct'] > 0:
            insights.append(
                f'Highest click rate: department "{worst["dept"]}" at {worst["click_pct"]}% '
                f'({worst["clicked"]} of {worst["sent"]} recipients).'
            )
        no_click = [d for d in dept_data if d['click_pct'] == 0 and d['sent'] > 0]
        if no_click:
            names = ', '.join(f'"{d["dept"]}"' for d in no_click[:3])
            s = 's' if len(no_click) > 1 else ''
            insights.append(f'No clicks recorded in department{s}: {names}.')

    if ttc_data and any(ttc_data.get('data', [])):
        data      = ttc_data.get('data', [])
        immediate = data[0] if data else 0
        if immediate:
            s = 's' if immediate != 1 else ''
            insights.append(
                f'{immediate} click{s} occurred within 1 minute of delivery — '
                'likely from recipients acting on habit rather than reading the email.'
            )

    # Cumulative engagement curve insight
    if cum_data and cum_data.get('pct'):
        pcts  = cum_data['pct']
        hours = cum_data['hours']
        final = pcts[-1]
        half_idx = next((i for i, p in enumerate(pcts) if p >= final / 2), None)
        if half_idx is not None and hours and final > 0:
            insights.append(
                f'50% of all engagements occurred within {hours[half_idx]:.0f} hour(s) of sending. '
                f'{final}% of targets engaged in total.'
            )

    # Click-to-submit speed insight
    if cts2_data and any(cts2_data.get('data', [])):
        data  = cts2_data['data']
        total = sum(data)
        if total:
            fast = data[0] + (data[1] if len(data) > 1 else 0)  # <30s + 30s-2m
            insights.append(
                f'{round(fast/total*100)}% of submitters entered credentials within '
                f'2 minutes of clicking — indicating low hesitation.'
            )

    # Device insight
    if device_os:
        dv = device_os.get('device', {})
        if dv.get('data') and sum(dv['data']):
            total = sum(dv['data'])
            labels = dv['labels']
            data_v = dv['data']
            mob_i = next((i for i, l in enumerate(labels) if 'mobile' in l.lower()), None)
            if mob_i is not None and data_v[mob_i]:
                insights.append(
                    f'{round(data_v[mob_i]/total*100)}% of interactions came from mobile devices.'
                )

    # A/B insight
    if ab_data and len(ab_data) >= 2:
        best  = max(ab_data, key=lambda v: v['click_pct'])
        worst = min(ab_data, key=lambda v: v['click_pct'])
        if best['click_pct'] != worst['click_pct']:
            insights.append(
                f'A/B test: variant "{best["variant"]}" had the highest click rate '
                f'({best["click_pct"]}%) vs "{worst["variant"]}" at {worst["click_pct"]}%.'
            )

    return insights


# ── Campaign Dashboard ────────────────────────────────────────────────────────

@admin.register(CampaignTracking)
class CampaignTrackingAdmin(StaffAccessMixin, admin.ModelAdmin):
    list_display  = ('name', 'status_badge', 'first_sent_col', 'finish_date_col',
                     'sent_count_col', 'events_col')
    list_filter   = ('status',)
    search_fields = ('name',)

    def get_urls(self):
        custom = [
            path('<path:object_id>/interactions/',
                 self.admin_site.admin_view(self.interactions_view),
                 name='tracking_campaigntracking_interactions'),
            path('<path:object_id>/report/',
                 self.admin_site.admin_view(self.report_view),
                 name='tracking_campaigntracking_report'),
        ]
        return custom + super().get_urls()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_staff

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _opened=Count('targets__interactions',
                          filter=Q(targets__interactions__event_type='opened')),
            _clicked=Count('targets__interactions',
                           filter=Q(targets__interactions__event_type='clicked')),
            _submitted=Count('targets__interactions',
                             filter=Q(targets__interactions__event_type='submitted')),
            _reported=Count('targets__interactions',
                            filter=Q(targets__interactions__event_type='reported')),
            _sent=Count('targets', filter=Q(targets__sent_at__isnull=False)),
        )

    def _ctx(self, request, campaign, **extra):
        return {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'campaign': campaign,
            **extra,
        }

    # ── Overview ──────────────────────────────────────────────────────────────

    def change_view(self, request, object_id, form_url='', extra_context=None):
        from apps.campaigns.models import CampaignTarget

        campaign = _load_campaign(object_id)
        counts   = _event_counts(campaign)
        sent     = _sent_count(campaign)

        cts = list(
            CampaignTarget.objects
            .filter(campaign=campaign, sent_at__isnull=False)
            .select_related('target__department')
        )
        raw = list(
            Interaction.objects
            .filter(campaign_target__campaign=campaign)
            .select_related('campaign_target__target__department')
            .order_by('event_timestamp')
        )

        dept_data     = _dept_breakdown(cts, raw)
        ttc_data      = _time_to_click_dist(cts, raw)
        provider_data = _email_providers(cts)
        risky_users   = _risky_users_campaign(cts, raw)
        offenders     = _repeat_offenders()
        ignored       = _ignored_count(cts, raw)
        heatmap       = _hourly_heatmap(raw)
        cum_data      = _cumulative_engagement(cts, raw)
        device_os     = _device_os_breakdown(raw)
        ab_data       = _ab_comparison(cts, raw)
        cts2_data     = _click_to_submit_delta(raw)
        callouts      = _chart_callouts(
            counts, sent, dept_data, ttc_data,
            heatmap, cum_data, device_os, cts2_data,
        )
        # Timeline callout
        day_ev = Counter()
        for i in raw:
            if i.event_type in ('clicked', 'submitted', 'mfa_submitted'):
                day_ev[i.event_timestamp.astimezone(_LOCAL_TZ).strftime('%Y-%m-%d')] += 1
        if day_ev:
            peak_day, peak_n = day_ev.most_common(1)[0]
            total_ev = sum(day_ev.values())
            callouts['timeline'] = (
                f'Peak activity: {peak_day} — {peak_n} engagement event{"s" if peak_n != 1 else ""} '
                f'({round(peak_n / total_ev * 100)}% of the total).'
            )

        ctx = self._ctx(request, campaign,
            title         = campaign.name,
            counts        = counts,
            sent_count    = sent,
            ignored_count = ignored,
            first_sent    = _first_sent(campaign),
            timeline_json = _build_timeline_json(raw),
            dept_json     = json.dumps({
                'depts':     [d['dept']      for d in dept_data],
                'clicked':   [d['clicked']   for d in dept_data],
                'submitted': [d['submitted'] for d in dept_data],
                'click_pct': [d['click_pct'] for d in dept_data],
            }),
            ttc_json      = json.dumps(ttc_data),
            provider_json = json.dumps(provider_data),
            heatmap_json  = json.dumps(heatmap),
            cum_json      = json.dumps(cum_data),
            device_json   = json.dumps(device_os),
            ab_json       = json.dumps(ab_data) if ab_data else 'null',
            cts2_json     = json.dumps(cts2_data),
            callouts      = callouts,
            risky_users   = risky_users,
            offenders     = offenders,
            active_tab    = 'overview',
        )
        ctx.update(extra_context or {})
        return TemplateResponse(
            request,
            'admin/tracking/campaigntracking/change_form.html',
            ctx,
        )

    # ── Interactions tab ──────────────────────────────────────────────────────

    def interactions_view(self, request, object_id):
        campaign = _load_campaign(object_id)

        if (request.method == 'POST'
                and request.user.is_superuser
                and getattr(settings, 'DEBUG', False)):
            iid = request.POST.get('delete_interaction')
            if iid:
                Interaction.objects.filter(
                    pk=iid, campaign_target__campaign=campaign
                ).delete()
            return HttpResponseRedirect(
                reverse('admin:tracking_campaigntracking_interactions', args=[object_id])
            )

        raw = list(
            Interaction.objects
            .filter(campaign_target__campaign=campaign)
            .select_related('campaign_target__target')
            .order_by('event_timestamp')
        )
        ctx = self._ctx(request, campaign,
            title        = f'{campaign.name} — Interactions',
            interactions = _enrich(raw, campaign),
            can_delete   = request.user.is_superuser and getattr(settings, 'DEBUG', False),
            active_tab   = 'interactions',
        )
        return TemplateResponse(
            request,
            'admin/tracking/campaigntracking/interactions.html',
            ctx,
        )

    # ── Report tab ────────────────────────────────────────────────────────────

    def report_view(self, request, object_id):
        from apps.campaigns.models import CampaignTarget
        from django.utils import timezone as tz

        campaign   = _load_campaign(object_id)
        counts     = _event_counts(campaign)
        sent       = _sent_count(campaign)
        first_sent = _first_sent(campaign)

        report = None
        if request.method == 'POST':
            inc_funnel       = 'include_funnel'   in request.POST
            inc_log          = 'include_log'       in request.POST
            inc_dept_table   = 'include_dept'      in request.POST
            inc_targets      = 'include_targets'   in request.POST
            inc_timeline     = 'include_timeline'  in request.POST
            inc_dept_chart   = 'include_dept_chart'in request.POST
            inc_ttc_chart    = 'include_ttc_chart' in request.POST
            exclude_scanners = 'exclude_scanners'  in request.POST
            notes            = request.POST.get('notes', '').strip()

            # Load all interactions once
            all_raw = list(
                Interaction.objects
                .filter(campaign_target__campaign=campaign)
                .select_related('campaign_target__target__department')
                .order_by('event_timestamp')
            )

            # Apply scanner filter to ALL analytics data when requested
            analytics_raw = [i for i in all_raw if not _is_scanner_ua(i)] if exclude_scanners else all_raw

            # Effective counts for funnel (scanner-filtered)
            if exclude_scanners:
                eff = defaultdict(int)
                for i in analytics_raw:
                    eff[i.event_type] += 1
                funnel_counts = dict(eff)
            else:
                funnel_counts = counts

            cts = list(
                CampaignTarget.objects
                .filter(campaign=campaign, sent_at__isnull=False)
                .select_related('target__department')
            )

            dept_data  = _dept_breakdown(cts, analytics_raw)
            ttc_data   = _time_to_click_dist(cts, analytics_raw)
            cum_data   = _cumulative_engagement(cts, analytics_raw)
            cts2_data  = _click_to_submit_delta(analytics_raw)
            device_os  = _device_os_breakdown(analytics_raw)
            ab_data    = _ab_comparison(cts, analytics_raw)
            ignored    = _ignored_count(cts, analytics_raw)
            risky      = _risky_users_campaign(cts, analytics_raw) if inc_targets else []

            interactions = []
            if inc_log:
                enriched = _enrich(all_raw, campaign)
                if exclude_scanners:
                    enriched = [i for i in enriched if not _is_scanner_ua(i)]
                interactions = enriched

            report = {
                'include_funnel':    inc_funnel,
                'include_log':       inc_log,
                'include_dept':      inc_dept_table,
                'include_targets':   inc_targets,
                'include_timeline':  inc_timeline,
                'include_dept_chart':inc_dept_chart,
                'include_ttc_chart': inc_ttc_chart,
                'exclude_scanners':  exclude_scanners,
                'notes':             notes,
                'funnel':            _funnel(funnel_counts, sent) if inc_funnel else [],
                'interactions':      interactions,
                'dept_data':         dept_data if inc_dept_table else [],
                'risky_users':       risky,
                'ignored_count':     ignored,
                'insights':          _generate_report_insights(
                    funnel_counts, sent, dept_data, ttc_data,
                    cum_data, cts2_data, device_os, ab_data,
                ),
                'timeline_json':     _build_timeline_json(analytics_raw) if inc_timeline else 'null',
                'dept_json':         json.dumps({
                    'depts':     [d['dept']      for d in dept_data],
                    'click_pct': [d['click_pct'] for d in dept_data],
                    'clicked':   [d['clicked']   for d in dept_data],
                    'submitted': [d['submitted'] for d in dept_data],
                }) if inc_dept_chart else 'null',
                'ttc_json':          json.dumps(ttc_data) if inc_ttc_chart else 'null',
                'generated_at':      tz.now(),
                'generated_by':      request.user.email,
            }

        ctx = self._ctx(request, campaign,
            title      = f'{campaign.name} — Report',
            counts     = counts,
            sent_count = sent,
            first_sent = first_sent,
            report     = report,
            active_tab = 'report',
        )
        return TemplateResponse(
            request,
            'admin/tracking/campaigntracking/report.html',
            ctx,
        )

    # ── List columns ──────────────────────────────────────────────────────────

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {
            'draft': '#8a8886', 'scheduled': '#0078d4',
            'running': '#107c10', 'completed': '#605e5c', 'finished': '#323130',
        }
        c = colours.get(obj.status, '#333')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:3px;'
            'font-size:11px;font-weight:600;text-transform:uppercase">{}</span>',
            c, obj.status,
        )

    @admin.display(description='First sent')
    def first_sent_col(self, obj):
        from apps.campaigns.models import CampaignTarget
        ts = (CampaignTarget.objects
              .filter(campaign=obj, sent_at__isnull=False)
              .order_by('sent_at')
              .values_list('sent_at', flat=True)
              .first())
        if not ts:
            return format_html('<span style="color:#8a8886">—</span>')
        return ts.astimezone(_LOCAL_TZ).strftime('%Y-%m-%d %H:%M')

    @admin.display(description='Finish date')
    def finish_date_col(self, obj):
        if not obj.finish_date:
            return format_html('<span style="color:#8a8886">—</span>')
        return obj.finish_date.astimezone(_LOCAL_TZ).strftime('%Y-%m-%d %H:%M')

    @admin.display(description='Sent')
    def sent_count_col(self, obj):
        return obj._sent

    @admin.display(description='O / C / S / R')
    def events_col(self, obj):
        return format_html(
            '<b style="color:#0078d4">{}</b> / <b style="color:#ff8c00">{}</b> / '
            '<b style="color:#d13438">{}</b> / <b style="color:#107c10">{}</b>',
            obj._opened, obj._clicked, obj._submitted, obj._reported,
        )
