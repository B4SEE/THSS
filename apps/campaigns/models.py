from django.db import models
from django.conf import settings


class SenderProfile(models.Model):
    """A named sending identity (From address) that can be assigned to campaigns."""
    display_name = models.CharField(max_length=100)
    email        = models.EmailField()
    reply_to     = models.EmailField(blank=True)
    is_active    = models.BooleanField(default=True)
    notes        = models.TextField(blank=True, help_text='Internal notes: which API key, domain, etc.')

    class Meta:
        db_table = 'sender_profiles'

    def __str__(self):
        return f'{self.display_name} <{self.email}>'

    @property
    def formatted(self):
        return f'{self.display_name} <{self.email}>'


class Template(models.Model):
    class Difficulty(models.TextChoices):
        LOW    = 'low',    'Low'
        MEDIUM = 'medium', 'Medium'
        HIGH   = 'high',   'High'

    name                = models.CharField(max_length=255)
    subject             = models.CharField(max_length=255)
    body                = models.TextField()
    difficulty_level    = models.CharField(max_length=10, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    category            = models.CharField(max_length=100, blank=True)
    educational_content = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'templates'

    def __str__(self):
        return f'[{self.difficulty_level}] {self.name}'


class Campaign(models.Model):
    class TargetType(models.TextChoices):
        ALL        = 'all',        'All Targets'
        DEPARTMENT = 'department', 'By Department'
        GROUP      = 'group',      'By Target Group'
        INDIVIDUAL = 'individual', 'Individual Selection'

    class Status(models.TextChoices):
        DRAFT     = 'draft',     'Draft'
        SCHEDULED = 'scheduled', 'Scheduled'
        RUNNING   = 'running',   'Running'
        COMPLETED = 'completed', 'Completed'
        FINISHED  = 'finished',  'Finished'

    name               = models.CharField(max_length=255)
    description        = models.TextField(blank=True, null=True, help_text='Optional internal notes or campaign description.')
    template           = models.ForeignKey(Template, on_delete=models.PROTECT, related_name='campaigns')
    sender             = models.ForeignKey(
        SenderProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='campaigns',
    )
    target_type         = models.CharField(max_length=15, choices=TargetType.choices, default=TargetType.ALL)
    target_departments  = models.ManyToManyField(
        'organizations.Department', blank=True, related_name='department_campaigns',
        help_text='Used when Target Type is "By Department". Select one or more departments.',
    )
    target_groups       = models.ManyToManyField(
        'targets.TargetGroup', blank=True, related_name='group_campaigns',
        help_text='Used when Target Type is "By Target Group". Select one or more groups.',
    )
    individual_targets = models.ManyToManyField(
        'targets.Target', blank=True, related_name='individual_campaigns',
        help_text='Used when Target Type is "Individual Selection"',
    )
    excluded_targets = models.ManyToManyField(
        'targets.Target', blank=True, related_name='excluded_campaigns',
        help_text='Targets explicitly excluded from receiving this campaign.',
    )
    scheduled_date     = models.DateTimeField(
        null=True, blank=True,
        help_text='Leave blank to send manually without auto-scheduling.',
    )
    finish_date        = models.DateTimeField(
        null=True, blank=True,
        help_text='Optional: tracking links auto-disable after this date/time. '
                  'Leave blank to disable only via the Finish action.',
    )
    status             = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    created_by         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_campaigns',
    )
    approved_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_campaigns',
    )
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'campaigns'

    def __str__(self):
        return f'{self.name} ({self.status})'


class CampaignTarget(models.Model):
    """Tracks which Target was sent an email for a Campaign, and when."""
    campaign   = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='targets')
    target     = models.ForeignKey('targets.Target', on_delete=models.CASCADE, related_name='campaign_targets')
    variant    = models.CharField(max_length=50, blank=True)
    sent_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table       = 'campaign_targets'
        unique_together = ('campaign', 'target')

    def __str__(self):
        return f'{self.campaign.name} → {self.target.email}'


class ABTest(models.Model):
    campaign              = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='ab_tests')
    variant_name          = models.CharField(max_length=50)
    template              = models.ForeignKey(Template, on_delete=models.PROTECT, related_name='ab_tests')
    allocation_percentage = models.PositiveIntegerField()
    subject_override      = models.CharField(
        max_length=255, blank=True,
        help_text='Override just the email subject. Leave blank to use the template subject.',
    )
    sender                = models.ForeignKey(
        SenderProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ab_tests',
        help_text='Override sender identity for this variant. Leave blank to use campaign sender.',
    )

    class Meta:
        db_table = 'ab_tests'

    def __str__(self):
        return f'{self.campaign.name} – {self.variant_name} ({self.allocation_percentage}%)'
