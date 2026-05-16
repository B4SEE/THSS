from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.organizations.models import Department
from apps.targets.models import Target, TargetGroup
from apps.campaigns.models import Campaign, Template, SenderProfile

MS365_BODY = """<div style="font-family:'Segoe UI',Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0078d4;padding:20px 24px">
    <tr><td>
      <table cellpadding="0" cellspacing="0"><tr>
        <td style="background:#f25022;width:10px;height:10px"></td><td style="width:2px"></td>
        <td style="background:#7fba00;width:10px;height:10px"></td>
      </tr><tr><td style="height:2px" colspan="3"></td></tr><tr>
        <td style="background:#00a4ef;width:10px;height:10px"></td><td style="width:2px"></td>
        <td style="background:#ffb900;width:10px;height:10px"></td>
      </tr></table>
      &nbsp;&nbsp;<span style="color:#fff;font-size:20px;font-weight:600;vertical-align:middle">Microsoft</span>
    </td></tr>
  </table>
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f2f1">
    <tr><td style="padding:0 24px 24px">
      <div style="background:#fff;padding:32px">
        <p style="margin:0 0 4px;font-size:13px;color:#605e5c">Action required &middot; {{full_name}}</p>
        <h2 style="margin:0 0 20px;font-size:22px;color:#323130;font-weight:600">Your password is expiring</h2>
        <p style="margin:0 0 16px;font-size:14px;color:#323130;line-height:22px">
          Your Microsoft 365 account password will expire in <strong style="color:#d13438">24 hours</strong>.
          After expiry you will lose access to Outlook, Teams, SharePoint, and all Microsoft 365 services.
        </p>
        <table cellpadding="0" cellspacing="0" style="margin-bottom:28px">
          <tr><td style="background:#0078d4;padding:10px 24px;border-radius:2px">
            <a href="{{click_url}}" style="color:#fff;text-decoration:none;font-size:15px;font-weight:600">
              Update password now
            </a>
          </td></tr>
        </table>
        <p style="margin:0 0 8px;font-size:12px;color:#605e5c;line-height:18px">
          If you did not request this, ignore this email.
          To report it as suspicious, <a href="{{report_url}}" style="color:#0078d4">click here</a>.
        </p>
        <hr style="border:none;border-top:1px solid #edebe9;margin:20px 0">
        <p style="margin:0;font-size:11px;color:#a19f9d">
          Microsoft Corporation &middot; One Microsoft Way &middot; Redmond, WA 98052<br>
          &copy; Microsoft 2025. All rights reserved.
        </p>
      </div>
    </td></tr>
  </table>
</div>"""

CTU_BODY = """<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:0 auto;color:#1b1b1b;background:#fff">
  <div style="background:#f2f2f2;border-bottom:1px solid #d0d0d0;padding:10px 20px;font-size:12px;color:#666;line-height:1.5">
    Tento email byl odeslán ze studijního informačního systému KOS.
  </div>
  <div style="padding:28px 24px">
    <p style="margin:0 0 16px;font-size:14px;line-height:1.7">Milí studenti programu SIT,</p>
    <p style="margin:0 0 16px;font-size:14px;line-height:1.7">
      jako každý semestr Vám zasíláme žádost o vyplnění <strong>povinného hodnocení předmětů</strong>
      za letní semestr 2024/2025. Vaše zpětná vazba je pro nás velmi důležitá &mdash; na základě
      hodnocení průběžně upravujeme obsah a výuku jednotlivých předmětů.
    </p>
    <p style="margin:0 0 16px;font-size:14px;line-height:1.7">
      Prosím vyplňte hodnocení <strong>nejpozději do {{deadline}}</strong>.
      Buďte prosím konkrétní a uveďte i nápady, jak by bylo možné jednotlivé předměty zlepšit.
      Pro přístup k formuláři je nutné se přihlásit pomocí svého ČVUT účtu.
    </p>
    <table cellpadding="0" cellspacing="0" style="margin:24px 0">
      <tr><td style="background:#1967d2;border-radius:4px;padding:11px 22px">
        <a href="{{click_url}}" style="color:#fff;text-decoration:none;font-size:14px;font-weight:600;letter-spacing:.1px">
          Přejít na hodnocení předmětů &rarr;
        </a>
      </td></tr>
    </table>
    <p style="margin:0 0 24px;font-size:14px;line-height:1.7">
      Ať se Vám daří v semestru i v průběhu zkouškového období!
    </p>
    <p style="margin:0;font-size:14px;line-height:1.9">
      Za radu studijního programu SIT<br>
      J.&nbsp;Šebek
    </p>
    <hr style="border:none;border-top:1px solid #e6e6e6;margin:24px 0">
    <p style="font-size:11px;color:#aaa;line-height:1.6;margin:0">
      Tuto zprávu považujete za podezřelou?
      <a href="{{report_url}}" style="color:#1967d2;text-decoration:none">Nahlásit jako phishing</a>
    </p>
  </div>
</div>"""

CTU_EDUCATIONAL = """Varovné signály v tomto e-mailu:

1. ODESÍLATEL — Adresa odesílatele nepocházela z domény @fel.cvut.cz ani @cvut.cz. Zobrazené jméno lze libovolně napodobit — vždy zkontrolujte celou e-mailovou adresu za symbolem @.
2. ODKAZ — Tlačítko nevedlo na kos.cvut.cz ani logon.ms.cvut.cz. Před kliknutím najeďte myší na odkaz a zkontrolujte URL v liště prohlížeče.
3. NALÉHAVOST — Deadline vytváří časový tlak, který omezuje čas na ověření legitimity zprávy.
4. POSTUP — Hodnocení přes KOS je dostupné přímo na kos.cvut.cz — není nutné klikat na odkaz v e-mailu.

Jak jednat příště:
- Zkontrolujte celou e-mailovou adresu odesílatele (ne jen zobrazené jméno).
- Najeďte myší na odkaz a ověřte doménu ještě před kliknutím.
- V případě pochybností přejděte na stránku zadáním adresy ručně do prohlížeče.
- Podezřelé e-maily nahlaste na helpdesk@fel.cvut.cz."""

TEST_BODY = """<div style="font-family:'Segoe UI',Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto;background:#f9f9f9;border:1px solid #ddd">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0078d4;padding:20px 24px">
    <tr><td style="color:#fff;font-size:16px;font-weight:700">Security Awareness</td></tr>
  </table>
  <div style="background:#fff;padding:28px">
    <p style="margin:0 0 4px;font-size:13px;color:#605e5c">Phishing simulation &middot; {{full_name}}</p>
    <h2 style="margin:0 0 16px;font-size:20px;color:#323130;font-weight:600">This is a phishing simulation test</h2>
    <p style="margin:0 0 14px;font-size:14px;color:#323130;line-height:22px">
      You are receiving this email as part of a <strong>testing the simulation app</strong>. This is <em>not</em> a real threat.
    </p>
    <p style="margin:0 0 20px;font-size:14px;color:#323130;line-height:22px">
      Please choose one of the following actions to complete the test:
    </p>
    <table cellpadding="0" cellspacing="0" style="margin-bottom:24px">
      <tr>
        <td style="padding-right:8px;padding-bottom:8px">
          <a href="{{click_url}}" style="display:inline-block;background:#0078d4;color:#fff;padding:10px 20px;text-decoration:none;font-size:14px;font-weight:600">Submit the form</a>
        </td>
        <td style="padding-right:8px;padding-bottom:8px">
          <a href="{{report_url}}" style="display:inline-block;background:#107c10;color:#fff;padding:10px 20px;text-decoration:none;font-size:14px;font-weight:600">Report as phishing</a>
        </td>
        <td style="padding-bottom:8px;vertical-align:middle">
          <span style="font-size:13px;color:#605e5c">Or simply ignore this email.</span>
        </td>
      </tr>
    </table>
    <hr style="border:none;border-top:1px solid #edebe9;margin:20px 0">
    <p style="margin:0;font-size:11px;color:#a19f9d;line-height:18px">
      This message was sent as part of a security awareness exercise.<br>
      No real credentials or personal data will be collected.
    </p>
  </div>
</div>"""

TEST_EDUCATIONAL = """This was a simulated phishing test.

The purpose of this exercise:
- Help you recognise how phishing emails are constructed
- Practice the report-as-phishing workflow
- Build security awareness within the organisation

In a real attack, the email would not announce itself. Stay vigilant:
- Verify unexpected requests by contacting the sender through a known channel.
- Report suspicious emails to your security team immediately."""

MS365_EDUCATIONAL = """Red flags in this email:

1. URGENCY - "Expires in 24 hours" creates panic so you act before thinking.
2. THREAT - "Lose access to all services" amplifies fear unnecessarily.
3. LINK - The URL behind "Update password now" is NOT microsoft.com or microsoftonline.com.
4. SENDER - The From address is not from Microsoft or your organisation's domain.
5. PROCESS - Password changes happen through your IT portal, never via an emailed link.

What to do next time:
- Hover before you click. The URL must match the legitimate domain exactly.
- When in doubt, open the site directly by typing the address yourself.
- Report suspicious emails to your security team immediately."""


class Command(BaseCommand):
    help = 'Seed database with test departments, targets, groups, templates, and a sample campaign.'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Delete existing seed data first')

    def handle(self, *args, **options):
        if options['clear']:
            self._clear()

        User = get_user_model()
        self.stdout.write('\n--- Admin Users ---')
        for email, name in [('admin_A@demo.local', 'Admin A'), ('admin_B@demo.local', 'Admin B')]:
            user, created = User.objects.get_or_create(
                email=email,
                defaults={'full_name': name, 'is_staff': True, 'is_superuser': False},
            )
            if created:
                user.set_password('admin1234')
                user.save()
            self.stdout.write(f'  {"[+]" if created else "[ ]"} {email}')

        self.stdout.write('\n--- Departments ---')
        depts = {}
        for name in ('Engineering', 'Marketing', 'Finance', 'HR', 'IT Security'):
            dept, created = Department.objects.get_or_create(name=name)
            depts[name] = dept
            self.stdout.write(f'  {"[+]" if created else "[ ]"} {name}')

        self.stdout.write('\n--- Targets ---')
        test_targets = [
            ('alice.test@phishsim.local',  'Alice Johnson',  'Engineering'),
            ('bob.test@phishsim.local',    'Bob Smith',      'Marketing'),
            ('carol.test@phishsim.local',  'Carol Davis',    'Finance'),
            ('david.test@phishsim.local',  'David Wilson',   'HR'),
            ('eve.test@phishsim.local',    'Eve Martinez',   'IT Security'),
        ]
        targets = []
        for email, full_name, dept_name in test_targets:
            t, created = Target.objects.get_or_create(
                email=email,
                defaults={'full_name': full_name, 'department': depts[dept_name]},
            )
            targets.append(t)
            self.stdout.write(f'  {"[+]" if created else "[ ]"} {email}')

        self.stdout.write('\n--- Target Groups ---')
        group, created = TargetGroup.objects.get_or_create(
            name='All Staff',
            defaults={'description': 'All test targets'},
        )
        group.members.set(targets)
        self.stdout.write(f'  {"[+]" if created else "[ ]"} All Staff ({len(targets)} members)')

        eng_group, created = TargetGroup.objects.get_or_create(
            name='Engineering',
            defaults={'description': 'Engineering department targets'},
        )
        eng_targets = [t for t in targets if t.department.name == 'Engineering']
        eng_group.members.set(eng_targets)
        self.stdout.write(f'  {"[+]" if created else "[ ]"} Engineering ({len(eng_targets)} members)')

        self.stdout.write('\n--- Sender Profiles ---')
        sender, created = SenderProfile.objects.get_or_create(
            email='security@inforrnation.com',
            defaults={'display_name': 'IT Security Team', 'is_active': True},
        )
        self.stdout.write(f'  {"[+]" if created else "[ ]"} {sender}')

        sebek_sender, created = SenderProfile.objects.get_or_create(
            email='sebekji1.fel.cvut.cz@inforrnation.com',
            defaults={'display_name': 'J. Šebek', 'is_active': True},
        )
        self.stdout.write(f'  {"[+]" if created else "[ ]"} {sebek_sender}')

        self.stdout.write('\n--- Templates ---')
        tmpl, created = Template.objects.get_or_create(
            name='Microsoft 365 - Password Expiry',
            defaults={
                'subject':             'Action required: Your Microsoft 365 password expires in 24 hours',
                'body':                MS365_BODY,
                'difficulty_level':    Template.Difficulty.HIGH,
                'category':            'microsoft365',
                'educational_content': MS365_EDUCATIONAL,
            },
        )
        self.stdout.write(f'  {"[+]" if created else "[ ]"} {tmpl.name}')

        ctu_tmpl, created = Template.objects.update_or_create(
            name='CTU — Hodnocení předmětů (J. Šebek)',
            defaults={
                'subject':             'Povinné hodnocení předmětů LS 2024/2025 — SIT',
                'body':                CTU_BODY,
                'difficulty_level':    Template.Difficulty.MEDIUM,
                'category':            'ctu',
                'educational_content': CTU_EDUCATIONAL,
            },
        )
        self.stdout.write(f'  {"[+]" if created else "[u]"} {ctu_tmpl.name}')

        test_tmpl, created = Template.objects.update_or_create(
            name='Test - Phishing Simulation Awareness',
            defaults={
                'subject':             '[Security Test] Phishing simulation — please respond',
                'body':                TEST_BODY,
                'difficulty_level':    Template.Difficulty.LOW,
                'category':            'microsoft365',
                'educational_content': TEST_EDUCATIONAL,
            },
        )
        self.stdout.write(f'  {"[+]" if created else "[u]"} {test_tmpl.name}')

        self.stdout.write('\n--- Campaign ---')
        camp, created = Campaign.objects.get_or_create(
            name='Q4 Security Awareness Simulation',
            defaults={
                'template':      tmpl,
                'sender':        sender,
                'target_type':   Campaign.TargetType.GROUP,
                'scheduled_date': timezone.now(),
                'status':        Campaign.Status.DRAFT,
            },
        )
        if created:
            camp.target_groups.set([group])
        self.stdout.write(f'  {"[+]" if created else "[ ]"} {camp.name} (id={camp.id})')

        ctu_camp, created = Campaign.objects.get_or_create(
            name='CTU SIT — Hodnocení předmětů (simulace)',
            defaults={
                'template':      ctu_tmpl,
                'sender':        sebek_sender,
                'target_type':   Campaign.TargetType.GROUP,
                'scheduled_date': timezone.now(),
                'status':        Campaign.Status.DRAFT,
            },
        )
        if created:
            ctu_camp.target_groups.set([group])
        self.stdout.write(f'  {"[+]" if created else "[ ]"} {ctu_camp.name} (id={ctu_camp.id})\n')
        self.stdout.write(self.style.SUCCESS('Seed complete.\n'))
        self.stdout.write('Next steps:')
        self.stdout.write('  1. python manage.py runserver')
        self.stdout.write('  2. Log in at http://localhost:8000/admin/')
        self.stdout.write('  3. Approve the campaign, then send it.')

    def _clear(self):
        Campaign.objects.filter(name__in=(
            'Q4 Security Awareness Simulation',
            'CTU SIT — Hodnocení předmětů (simulace)',
        )).delete()
        Template.objects.filter(name__in=(
            'Microsoft 365 - Password Expiry',
            'CTU - Password Change Notice',
            'CTU — Hodnocení předmětů (J. Šebek)',
            'Test - Phishing Simulation Awareness',
        )).delete()
        TargetGroup.objects.filter(name__in=('All Staff', 'Engineering')).delete()
        Target.objects.filter(email__endswith='@phishsim.local').delete()
        self.stdout.write(self.style.WARNING('Cleared seed data.\n'))
