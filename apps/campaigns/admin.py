from django import forms
from django.conf import settings as django_settings
from django.contrib import admin
from django.contrib.admin.widgets import AdminSplitDateTime
from django.db.models import Count
from django.forms import BaseInlineFormSet
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.admin_mixins import StaffAccessMixin, audit as _audit_base
from .models import SenderProfile, Template, Campaign, CampaignTarget, ABTest
from .service import CampaignService


# ── Helpers ───────────────────────────────────────────────────────────────────

def _campaign_snapshot(campaign):
    """Stable snapshot of a campaign included in every audit entry."""
    try:
        target_count = CampaignService._resolve_recipients(campaign)
        tc = len(target_count)
    except Exception:
        tc = '?'
    return {
        'campaign_name':   campaign.name,
        'campaign_status': campaign.status,
        'target_count':    tc,
    }


def _audit(request, action, campaign, changes=None):
    merged = {**_campaign_snapshot(campaign), **(changes or {})}
    _audit_base(request, action, campaign, changes=merged)


# ── Actions ───────────────────────────────────────────────────────────────────

@admin.action(description='Approve selected campaigns')
def approve_campaign(modeladmin, request, queryset):
    if not request.user.is_superuser:
        modeladmin.message_user(request, 'Only superadmins can approve campaigns.', level='error')
        return
    now = timezone.now()
    approved = []
    for campaign in queryset.filter(approved_by__isnull=True):
        campaign.approved_by = request.user
        campaign.status = (
            Campaign.Status.SCHEDULED
            if campaign.scheduled_date and campaign.scheduled_date > now
            else Campaign.Status.DRAFT
        )
        campaign.save(update_fields=['approved_by', 'status'])
        _audit(request, 'campaign_approved', campaign)
        approved.append(campaign)
    modeladmin.message_user(request, f'{len(approved)} campaign(s) approved and scheduled.')


@admin.action(description='Finish campaign — deactivates all tracking links')
def finish_campaign(modeladmin, request, queryset):
    for campaign in queryset.exclude(status=Campaign.Status.FINISHED):
        campaign.status = Campaign.Status.FINISHED
        campaign.save(update_fields=['status', 'updated_at'])
        _audit(request, 'campaign_finished', campaign)
    modeladmin.message_user(request, f'{queryset.count()} campaign(s) marked as finished.')


@admin.action(description='Reset to Draft — clears approval and send history')
def reset_to_draft(modeladmin, request, queryset):
    if not request.user.is_superuser:
        modeladmin.message_user(request, 'Only superadmins can reset campaigns.', level='error')
        return
    for campaign in queryset:
        CampaignService.reset(campaign)
        _audit(request, 'campaign_reset', campaign)
    modeladmin.message_user(request, f'{queryset.count()} campaign(s) reset to Draft.')


@admin.action(description='Copy campaign — new draft with same settings, no send history')
def copy_campaign(modeladmin, request, queryset):
    last = None
    for campaign in queryset:
        new = Campaign(
            name=f'Copy of {campaign.name}',
            description=campaign.description,
            template=campaign.template,
            sender=campaign.sender,
            target_type=campaign.target_type,
            status=Campaign.Status.DRAFT,
            created_by=request.user,
        )
        new.save()
        new.target_departments.set(campaign.target_departments.all())
        new.target_groups.set(campaign.target_groups.all())
        new.individual_targets.set(campaign.individual_targets.all())
        for ab in campaign.ab_tests.all():
            ABTest.objects.create(
                campaign=new,
                variant_name=ab.variant_name,
                template=ab.template,
                allocation_percentage=ab.allocation_percentage,
                subject_override=ab.subject_override,
                sender=ab.sender,
            )
        _audit(request, 'campaign_copied', new, changes={
            'copied_from_id': campaign.pk,
            'copied_from_name': campaign.name,
        })
        last = new
    if queryset.count() == 1 and last:
        return HttpResponseRedirect(
            reverse('admin:campaigns_campaign_change', args=[last.pk])
        )
    modeladmin.message_user(request, f'{queryset.count()} campaign(s) copied as new drafts.')


@admin.action(description='Send emails now — campaign must be approved first')
def send_now(modeladmin, request, queryset):
    svc = CampaignService()
    results = []
    for campaign in queryset:
        if not campaign.approved_by_id:
            results.append(f'"{campaign.name}": skipped — not approved')
            continue
        try:
            sent, failed, skipped, remaining = svc.send(campaign)
            suffix = f', {remaining} remaining' if remaining else ''
            results.append(f'"{campaign.name}": {sent} sent, {failed} failed, {skipped} skipped{suffix}')
            _audit(request, 'campaign_sent', campaign,
                   changes={'sent': sent, 'failed': failed, 'skipped': skipped})
        except Exception as exc:
            results.append(f'"{campaign.name}": ERROR — {exc}')
    modeladmin.message_user(request, ' | '.join(results))


# ── Sender Profile ─────────────────────────────────────────────────────────────

@admin.register(SenderProfile)
class SenderProfileAdmin(StaffAccessMixin, admin.ModelAdmin):
    list_display  = ('display_name', 'email', 'reply_to', 'is_active')
    list_filter   = ('is_active',)
    search_fields = ('display_name', 'email')
    fields        = ('display_name', 'email', 'reply_to', 'is_active', 'notes')


# ── Template ──────────────────────────────────────────────────────────────────

@admin.register(Template)
class TemplateAdmin(StaffAccessMixin, admin.ModelAdmin):
    list_display  = ('name', 'subject', 'difficulty_level', 'category', 'created_at')
    list_filter   = ('difficulty_level', 'category')
    search_fields = ('name', 'subject')


# ── Campaign ──────────────────────────────────────────────────────────────────

class CampaignForm(forms.ModelForm):
    scheduled_date = forms.SplitDateTimeField(
        required=False,
        widget=AdminSplitDateTime(),
        help_text='Leave blank to skip auto-scheduling and send manually.',
    )

    class Meta:
        model   = Campaign
        fields  = '__all__'
        widgets = {
            'excluded_targets': forms.MultipleHiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'individual_targets' in self.fields:
            from apps.targets.models import Target
            self.fields['individual_targets'].queryset = (
                Target.objects.filter(opt_out=False).select_related('department').order_by('full_name')
            )
        if 'excluded_targets' in self.fields:
            from apps.targets.models import Target
            self.fields['excluded_targets'].queryset = Target.objects.all()


class ABTestFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        total = sum(
            form.cleaned_data.get('allocation_percentage', 0)
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False)
        )
        if total > 100:
            raise forms.ValidationError(
                f'A/B variant allocations total {total}% — cannot exceed 100%. '
                f'The remaining {100 - min(total, 100)}% is the implicit control group (variant A).'
            )


class ABTestInline(admin.TabularInline):
    model   = ABTest
    formset = ABTestFormSet
    extra   = 0
    fields  = ('variant_name', 'template', 'subject_override', 'sender', 'allocation_percentage')


class SentTargetInline(admin.TabularInline):
    model           = CampaignTarget
    extra           = 0
    can_delete      = False
    readonly_fields = ('target', 'variant', 'sent_at')
    fields          = ('target', 'variant', 'sent_at')
    verbose_name_plural = 'Sent targets (tracking — read only)'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Campaign)
class CampaignAdmin(StaffAccessMixin, admin.ModelAdmin):
    form          = CampaignForm
    list_display  = ('name', 'template', 'sender', 'status_badge', 'approval_badge',
                     'target_type', 'sent_count', 'interaction_summary',
                     'interactions_link', 'created_by')
    list_filter   = ('status', 'target_type')
    search_fields = ('name',)
    readonly_fields   = ('created_at', 'updated_at', 'created_by', 'approved_by',
                         'interaction_summary', 'resolved_targets_preview', 'ab_variant_preview')
    filter_horizontal = ['target_departments', 'target_groups', 'individual_targets']
    inlines           = [ABTestInline, SentTargetInline]
    actions           = [approve_campaign, finish_campaign, send_now, copy_campaign, reset_to_draft]
    fieldsets = (
        ('Campaign', {
            'fields': ('name', 'description', 'template', 'sender', 'scheduled_date', 'finish_date', 'status'),
        }),
        ('Targeting', {
            'fields': ('target_type', 'target_departments', 'target_groups',
                       'individual_targets', 'resolved_targets_preview'),
            'description': (
                'Select a targeting mode. '
                'Department → choose one or more departments. '
                'Group → choose one or more groups. '
                'Individual → select targets directly. '
                'For department or group mode, use "Additional individual targets" '
                'to include extra people not in those groups/departments.'
            ),
        }),
        ('A/B Test Distribution', {
            'fields': ('ab_variant_preview',),
            'description': 'Expected recipient split based on A/B test configuration above.',
            'classes': ('collapse',),
        }),
        ('Approval & Metadata', {
            'fields': ('approved_by', 'created_by', 'created_at', 'updated_at', 'interaction_summary'),
            'classes': ('collapse',),
        }),
    )

    class Media:
        js = ('admin/campaigns/js/campaign_targeting.js',)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == 'scheduled_date' and field:
            field.required = False
        return field

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status in (Campaign.Status.COMPLETED, Campaign.Status.FINISHED):
            return django_settings.DEBUG
        return super().has_delete_permission(request)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            for name in ('approve_campaign', 'reset_to_draft'):
                actions.pop(name, None)
        if not django_settings.DEBUG:
            actions.pop('reset_to_draft', None)
        return actions

    def _full_reset_to_draft(self, obj):
        """Inline reset used when status is manually changed to Draft in the edit form."""
        obj.approved_by = None
        CampaignTarget.objects.filter(campaign=obj).update(sent_at=None)

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if not request.user.is_superuser:
            ro.append('status')
        if obj and obj.status != Campaign.Status.DRAFT and not request.user.is_superuser:
            ro += ['name', 'template', 'sender', 'target_type', 'target_departments',
                   'target_groups', 'individual_targets', 'scheduled_date']
        return ro

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        elif change:
            old = Campaign.objects.filter(pk=obj.pk).values('status', 'approved_by_id').first()
            if old:
                # Manually setting status back to Draft → full reset
                if obj.status == Campaign.Status.DRAFT and old['status'] != Campaign.Status.DRAFT:
                    self._full_reset_to_draft(obj)
                # Non-superadmin editing an approved campaign → requires re-approval
                elif old['approved_by_id'] and not request.user.is_superuser:
                    obj.approved_by = None
        super().save_model(request, obj, form, change)
        _audit(
            request,
            'campaign_updated' if change else 'campaign_created',
            obj,
            changes={'fields': form.changed_data} if change and form.changed_data else None,
        )

    # ── Display helpers ───────────────────────────────────────────────────────

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {'draft': '#8a8886', 'scheduled': '#0078d4',
                   'running': '#107c10', 'completed': '#605e5c', 'finished': '#323130'}
        c = colours.get(obj.status, '#333')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:3px;'
            'font-size:11px;font-weight:600;text-transform:uppercase">{}</span>', c, obj.status,
        )

    @admin.display(description='Approved')
    def approval_badge(self, obj):
        if obj.approved_by_id:
            return format_html(
                '<span style="color:#107c10;font-weight:600" title="Approved by {}">&#10003;</span>',
                obj.approved_by.email,
            )
        return format_html('<span style="color:#8a8886">&#8212;</span>')

    @admin.display(description='Sent')
    def sent_count(self, obj):
        return obj.targets.filter(sent_at__isnull=False).count()

    @admin.display(description='O/C/S/R')
    def interaction_summary(self, obj):
        from apps.tracking.models import Interaction
        rows    = (Interaction.objects.filter(campaign_target__campaign=obj)
                   .values('event_type').annotate(n=Count('id')))
        mapping = {r['event_type']: r['n'] for r in rows}
        return format_html(
            '<span title="Opened/Clicked/Submitted/Reported">'
            '<b style="color:#0078d4">{}</b> / <b style="color:#ff8c00">{}</b> / '
            '<b style="color:#d13438">{}</b> / <b style="color:#107c10">{}</b></span>',
            mapping.get('opened', 0), mapping.get('clicked', 0),
            mapping.get('submitted', 0), mapping.get('reported', 0),
        )

    @admin.display(description='Events log')
    def interactions_link(self, obj):
        from apps.tracking.models import Interaction
        count = Interaction.objects.filter(campaign_target__campaign=obj).count()
        if not count:
            return format_html('<span style="color:#8a8886">—</span>')
        url = reverse('admin:tracking_campaigntracking_interactions', args=[obj.pk])
        return format_html('<a href="{}">{} event(s)</a>', url, count)

    @admin.display(description='A/B variant split')
    def ab_variant_preview(self, obj):
        if not obj or not obj.pk:
            return '—'
        ab_tests = list(obj.ab_tests.select_related('template', 'sender').all())
        if not ab_tests:
            return format_html(
                '<span style="color:var(--body-quiet-color)">No A/B tests configured — '
                'all targets receive variant A (campaign template).</span>'
            )
        try:
            total = len(CampaignService._resolve_recipients(obj))
        except Exception:
            total = 0
        ab_total_pct = sum(ab.allocation_percentage for ab in ab_tests)
        control_pct  = max(0, 100 - ab_total_pct)
        lines = [format_html(
            '<b>A (control)</b>: ~{} targets ({}%) — <em>{}</em>',
            round(total * control_pct / 100), control_pct, obj.template,
        )]
        for ab in ab_tests:
            sender_note = f' · sender: {ab.sender}' if ab.sender else ''
            subj_note   = f' · subject: "{ab.subject_override}"' if ab.subject_override else ''
            lines.append(format_html(
                '<b>{}</b>: ~{} targets ({}%) — <em>{}</em>{}{}',
                ab.variant_name,
                round(total * ab.allocation_percentage / 100),
                ab.allocation_percentage,
                ab.template,
                subj_note,
                sender_note,
            ))
        if ab_total_pct > 100:
            lines.append(format_html(
                '<span style="color:#d13438;font-weight:600">'
                '⚠ Allocations sum to {}% — save to see validation error.</span>',
                ab_total_pct,
            ))
        return format_html('<br>'.join(str(l) for l in lines))

    @admin.display(description='Resolved targets')
    def resolved_targets_preview(self, obj):
        if not obj or not obj.pk:
            return '—'
        try:
            targets = CampaignService._resolve_recipients(obj)
        except Exception as exc:
            return format_html('<span style="color:#d13438">{}</span>', str(exc))
        if not targets:
            return format_html(
                '<span style="color:#8a8886">No targets resolved — check targeting settings.</span>'
            )
        rows = format_html(''.join(
            str(format_html(
                '<div class="rt-row" data-id="{}" style="display:flex;align-items:center;'
                'padding:3px 4px;border-bottom:1px solid #f0f0f0">'
                '<span style="flex:1;font-family:monospace;font-size:12px">{} &lt;{}&gt;</span>'
                '<button type="button" class="rt-remove" data-id="{}" title="Exclude from campaign" '
                'style="margin-left:8px;border:none;background:none;color:#a80000;font-size:16px;'
                'line-height:1;cursor:pointer;padding:0 4px;flex-shrink:0">×</button>'
                '</div>',
                t.pk, t.full_name, t.email, t.pk,
            ))
            for t in targets
        ))
        return format_html(
            '<div id="rt-count" style="margin-bottom:6px;font-size:12px;color:#555">'
            '{} target{} will receive this campaign'
            '<span id="rt-removed" style="color:#a80000;margin-left:6px"></span>'
            '</div>'
            '<input id="rt-search" type="text" placeholder="Search by name or email…" '
            'style="width:100%;box-sizing:border-box;margin-bottom:4px;padding:4px 6px;'
            'border:1px solid #ccc;border-radius:3px;font-size:12px">'
            '<div id="rt-list" style="max-height:320px;overflow-y:auto;border:1px solid #ddd;'
            'border-radius:3px;padding:2px">{}</div>',
            len(targets), 's' if len(targets) != 1 else '',
            rows,
        )
