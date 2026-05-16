from django.core.management.base import BaseCommand, CommandError
from apps.campaigns.models import Campaign
from apps.campaigns.service import CampaignService


class Command(BaseCommand):
    help = 'Send phishing simulation emails for a campaign (CLI shortcut — use admin for normal workflow)'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--id',   type=int, dest='campaign_id')
        group.add_argument('--name', type=str, dest='campaign_name')
        parser.add_argument('--force',   action='store_true', help='Reset and re-send a completed campaign')
        parser.add_argument('--dry-run', action='store_true', help='Show recipients without sending')

    def handle(self, *args, **options):
        campaign = self._get_campaign(options)
        dry_run  = options['dry_run']
        force    = options['force']

        self.stdout.write(f'\nCampaign : {campaign.name}')
        self.stdout.write(f'Status   : {campaign.status}')
        self.stdout.write(f'Template : {campaign.template.name}')

        if campaign.status == Campaign.Status.COMPLETED and not force and not dry_run:
            raise CommandError(
                'Campaign is already completed. Re-send with --force, or reset in the admin.'
            )

        if force:
            CampaignService.reset(campaign)
            campaign.refresh_from_db()

        recipients = CampaignService._resolve_recipients(campaign)
        if not recipients:
            raise CommandError('No eligible recipients.')

        self.stdout.write(f'Recipients: {len(recipients)}\n')

        if dry_run:
            for t in recipients:
                self.stdout.write(f'  [dry-run] {t.email}  ({t.full_name})')
            self.stdout.write(self.style.WARNING('\nDry run complete — nothing sent.'))
            return

        sent, failed, skipped, remaining = CampaignService().send(campaign)
        self.stdout.write(
            self.style.SUCCESS(f'\nDone. Sent: {sent}  Failed: {failed}  Skipped: {skipped}')
        )
        if remaining:
            self.stdout.write(self.style.WARNING(f'Remaining: {remaining} — run again to continue.'))

    @staticmethod
    def _get_campaign(options) -> Campaign:
        try:
            if options['campaign_id']:
                return Campaign.objects.select_related('template').get(pk=options['campaign_id'])
            return Campaign.objects.select_related('template').get(name=options['campaign_name'])
        except Campaign.DoesNotExist:
            raise CommandError('Campaign not found.')
