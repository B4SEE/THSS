import zoneinfo

from django.contrib import admin
from django.conf import settings
from django.contrib import messages
from django.utils.html import format_html

from apps.admin_mixins import StaffAccessMixin
from .models import AuditLog

_LOCAL_TZ = zoneinfo.ZoneInfo(settings.TIME_ZONE)

ACTION_COLOURS = {
    'login':          '#107c10',
    'logout':         '#605e5c',
    'login_failed':   '#d13438',
    'campaign_sent':  '#0078d4',
    'campaign_approved': '#107c10',
    'campaign_reset': '#ff8c00',
    'campaign_finished': '#323130',
    'target_deleted': '#d13438',
}


@admin.register(AuditLog)
class AuditLogAdmin(StaffAccessMixin, admin.ModelAdmin):
    list_display  = ('time_local', 'time_utc', 'actor_badge', 'ip_address',
                     'action_badge', 'entity_badge', 'details_summary')
    list_filter   = ('action', 'entity_type')
    search_fields = ('actor_email', 'actor_name', 'action', 'entity_type', 'ip_address')
    readonly_fields = ('timestamp', 'user', 'actor_email', 'actor_name', 'ip_address',
                       'action', 'entity_type', 'entity_id', 'changes')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # ── Display columns ───────────────────────────────────────────────────────

    @admin.display(description='Local time', ordering='timestamp')
    def time_local(self, obj):
        local = obj.timestamp.astimezone(_LOCAL_TZ)
        return local.strftime('%Y-%m-%d %H:%M:%S')

    @admin.display(description='UTC', ordering='timestamp')
    def time_utc(self, obj):
        return format_html(
            '<span style="color:#8a8886;font-size:12px">{}</span>',
            obj.timestamp.strftime('%H:%M:%S'),
        )

    @admin.display(description='Actor')
    def actor_badge(self, obj):
        name = obj.actor_name or obj.actor_email or '—'
        email = obj.actor_email
        if email and name != email:
            return format_html(
                '<span title="{}">{}</span>',
                email, name,
            )
        return name

    @admin.display(description='Action')
    def action_badge(self, obj):
        colour = ACTION_COLOURS.get(obj.action, '#333')
        return format_html(
            '<span style="color:{};font-weight:600">{}</span>',
            colour, obj.action,
        )

    @admin.display(description='Object')
    def entity_badge(self, obj):
        if not obj.entity_type:
            return '—'
        if obj.entity_id:
            return format_html('{} <span style="color:#8a8886">#{}</span>',
                               obj.entity_type, obj.entity_id)
        return obj.entity_type

    @admin.display(description='Details')
    def details_summary(self, obj):
        if not obj.changes:
            return '—'
        c = obj.changes
        parts = []
        # Campaign snapshot
        if 'campaign_name' in c:
            parts.append(c['campaign_name'])
        if 'campaign_status' in c:
            parts.append(f'status={c["campaign_status"]}')
        if 'sent' in c:
            parts.append(f'sent={c["sent"]} failed={c.get("failed", 0)}')
        if 'attempted_email' in c:
            parts.append(f'tried={c["attempted_email"]}')
        if 'fields' in c:
            parts.append(f'fields={",".join(c["fields"])}')
        if not parts:
            # Fallback: first 60 chars of JSON
            import json
            raw = json.dumps(c)
            parts.append(raw[:60] + ('…' if len(raw) > 60 else ''))
        return ' · '.join(parts)

    # ── Clear logs action (ALLOW_LOG_CLEAR gate) ──────────────────────────────

    def get_actions(self, request):
        actions = super().get_actions(request)
        if settings.ALLOW_LOG_CLEAR and request.user.is_superuser:
            actions['clear_all_logs'] = (
                self._clear_all_logs,
                'clear_all_logs',
                'Clear ALL audit logs',
            )
        return actions

    def _clear_all_logs(self, modeladmin, request, queryset):
        count, _ = AuditLog.objects.all().delete()
        self.message_user(request, f'Deleted {count} audit log entries.', messages.WARNING)
