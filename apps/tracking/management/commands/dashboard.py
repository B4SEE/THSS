import json
from datetime import datetime, timezone

import redis
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'

EVENT_STYLES = {
    'opened':    ('\033[94m', '📬'),  # blue
    'clicked':   ('\033[93m', '🖱️ '),  # yellow
    'submitted': ('\033[91m', '⚠️ '),  # red
    'reported':  ('\033[92m', '🚨'),  # green
}


def _now():
    return datetime.now(timezone.utc).strftime('%H:%M:%S')


class Command(BaseCommand):
    help = 'Live console dashboard — streams interaction events in real time via Redis pub/sub'

    def handle(self, *args, **options):
        self._print_header()
        self._print_current_stats()

        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        pubsub = r.pubsub()
        pubsub.subscribe('dashboard:events')

        self.stdout.write(f'\n{BOLD}Live feed{RESET} {DIM}(Ctrl+C to stop){RESET}\n')
        self.stdout.write('-' * 90 + '\n')

        try:
            for message in pubsub.listen():
                if message['type'] != 'message':
                    continue
                self._handle_event(message['data'])
        except KeyboardInterrupt:
            pubsub.unsubscribe()
            self.stdout.write(f'\n{DIM}Dashboard stopped.{RESET}\n')

    def _print_header(self):
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(f'{BOLD}  Phishing Simulation Platform -- Live Dashboard{RESET}')
        self.stdout.write('=' * 60 + '\n')

    def _print_current_stats(self):
        from apps.campaigns.models import Campaign
        from apps.tracking.models import Interaction

        campaigns = Campaign.objects.values('status').annotate(n=Count('id'))
        status_map = {r['status']: r['n'] for r in campaigns}

        interactions = Interaction.objects.values('event_type').annotate(n=Count('id'))
        event_map = {r['event_type']: r['n'] for r in interactions}

        self.stdout.write(f'{BOLD}Campaign status:{RESET}  ', ending='')
        for status in ('draft', 'scheduled', 'running', 'completed'):
            self.stdout.write(f'{status}={status_map.get(status, 0)}  ', ending='')
        self.stdout.write('')

        self.stdout.write(f'{BOLD}Total events:   {RESET}  ', ending='')
        for et in ('opened', 'clicked', 'submitted', 'reported'):
            color, icon = EVENT_STYLES.get(et, ('', ''))
            self.stdout.write(f'{color}{icon}{et}={event_map.get(et, 0)}{RESET}  ', ending='')
        self.stdout.write('\n')

    def _handle_event(self, raw):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return

        event_type = data.get('event_type', 'unknown')
        color, icon = EVENT_STYLES.get(event_type, ('', '  '))
        ts = data.get('timestamp', '')[:19].replace('T', ' ')

        self.stdout.write(
            f"[{DIM}{ts}{RESET}] "
            f"{color}{BOLD}{icon} {event_type.upper():<10}{RESET}"
            f"  {BOLD}campaign:{RESET} {data.get('campaign', '?'):<28}"
            f"  {BOLD}user:{RESET} {data.get('user_name', '?'):<22}"
            f"  {DIM}{data.get('user_email', '')}{RESET}"
            f"  {DIM}ip={data.get('ip_address', '-')}{RESET}"
        )
