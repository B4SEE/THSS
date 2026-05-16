import resend
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Send a test email to verify Resend configuration before running a real campaign'

    def add_arguments(self, parser):
        parser.add_argument('--to', required=True, help='Recipient email address for the test')

    def handle(self, *args, **options):
        to = options['to']

        self.stdout.write('\nResend configuration:')
        self.stdout.write(f'  API key  : {settings.RESEND_API_KEY[:8]}... (truncated)')
        self.stdout.write(f'  FROM     : {settings.DEFAULT_FROM_EMAIL}')
        self.stdout.write(f'  TO       : {to}\n')
        self.stdout.write('Sending...')

        resend.api_key = settings.RESEND_API_KEY

        try:
            result = resend.Emails.send({
                'from': settings.DEFAULT_FROM_EMAIL,
                'to': [to],
                'subject': '[Phishing Platform] Resend test — configuration works',
                'text': (
                    'This is a test email from your Phishing Simulation Platform.\n\n'
                    'If you received this, your Resend configuration is working correctly.\n'
                    'You can now run your campaign:\n\n'
                    '  python manage.py send_campaign --id <id>\n'
                ),
            })
            self.stdout.write(self.style.SUCCESS(
                f'OK — test email delivered to {to} (id: {result.get("id")})'
            ))
        except Exception as exc:
            raise CommandError(f'Failed to send: {exc}')
