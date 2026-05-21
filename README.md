# Phishing Simulation Platform — Source Code

https://github.com/B4SEE/THSS/tree/main

Django-based platform for running controlled phishing awareness campaigns.

## Directory Structure

```
THSS/
├── manage.py                   Django management entry point
├── docker-compose.yml          Infrastructure: PostgreSQL 16, Redis 7, MailHog
├── requirements.txt            All Python dependencies with pinned versions
├── gen_docs.py                 Regenerates HTML API docs via pdoc
├── restart_server.py           Dev helper: clears port 8000 and restarts the server
│
├── config/                     Django project configuration
│   ├── settings.py             All settings; reads .env for secrets
│   ├── urls.py                 Root URL routing
│   ├── asgi.py                 ASGI entry point (Daphne / Django Channels)
│   ├── wsgi.py                 WSGI entry point (fallback)
│   └── views.py                Custom 403/404/500 error handlers
│
├── apps/                       Application packages
│   ├── admin_mixins.py         Shared admin utilities: IP extraction, audit logging, role mixins
│   ├── organizations/          User model (email-based auth), Department hierarchy
│   ├── targets/                Target (email recipient), TargetGroup for bulk assignment
│   ├── campaigns/              Campaign, Template, SenderProfile, ABTest;
│   │   │                       CampaignService (sending logic), background Scheduler thread
│   │   └── management/commands/
│   │       ├── send_campaign.py    Send a campaign from the CLI (--dry-run / --force flags)
│   │       ├── import_users.py     Import targets from CSV (email, full_name, department, role)
│   │       ├── seed_test_data.py   Seed sample departments, targets, templates, campaigns
│   │       └── test_email.py       Send a test email to verify Resend API key
│   ├── emails/                 PhishingEmailService — wraps Resend API, injects tracking tokens
│   ├── tracking/               Interaction model, token validation, landing/feedback/pixel views
│   │   └── templates/tracking/
│   │       ├── phishing_microsoft365.html   Microsoft 365 credential-harvest landing page
│   │       ├── phishing_ctu.html            CTU landing page
│   │       ├── phishing_ctu_mfa.html        CTU MFA step page
│   │       ├── educational_feedback.html    Shown after credential submission
│   │       ├── educational_feedback_ctu.html
│   │       ├── reported.html                Shown after target reports the email
│   │       └── campaign_finished.html       Neutral page shown after campaign is closed
│   └── audit/                  AuditLog — append-only record of all admin actions
│
├── templates/                  Global admin template overrides
│   ├── admin/base_site.html    Custom branding for the Django admin
│   └── admin/debug_toggle.html Debug-mode toggle widget (shown only when DEBUG=True)
│
└── docs/                       Pre-generated HTML API documentation (pdoc)
                                Open docs/index.html in a browser to browse.
```

## Quick Start

**Requirements:** Python 3.11+, Docker Desktop.

```bash
docker-compose up -d

python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env          # edit RESEND_API_KEY and PLATFORM_BASE_URL

python manage.py migrate
python manage.py seed_test_data

python manage.py runserver
```

- Admin interface: http://localhost:8000/admin/
- Captured dev emails (MailHog): http://localhost:8025/

The `seed_test_data` command creates an admin account, credentials are printed to the console.

## Key Management Commands

```bash
python manage.py send_campaign --name "Campaign Name" --dry-run
python manage.py import_users targets.csv
python manage.py test_email
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `RESEND_API_KEY` | Yes | API key for the Resend email delivery service |
| `PLATFORM_BASE_URL` | Yes | Base URL used to build tracking links in emails |
| `SECRET_KEY` | Prod | Django secret key (defaults to an insecure dev value) |
| `EMAIL_SEND_DELAY` | No | Seconds between individual sends (default: 0) |
| `EMAIL_BATCH_SIZE` | No | Max emails per run; 0 = unlimited |
| `ALLOWED_HOSTS` | Prod | Space-separated list of allowed hostnames |

## Tracking URLs

All tracking endpoints follow `/t/<campaign-name>/<token>/`:

| Path | Event logged |
|---|---|
| `/t/<name>/<token>/` | `clicked` — landing page visited |
| `/t/<name>/<token>/pixel.gif` | `opened` — tracking pixel loaded |
| `/t/<name>/<token>/submit/` | `submitted` — credentials entered |
| `/t/<name>/<token>/report/` | `reported` — target reported the email |
| `/t/<name>/<token>/feedback/` | Educational feedback page (no event) |
