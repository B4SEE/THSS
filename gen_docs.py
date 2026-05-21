"""Run pdoc on all app modules after bootstrapping Django."""
import os, sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.test_settings')

import django
django.setup()

import pdoc
from pathlib import Path

modules = [
    'apps.organizations.models',
    'apps.targets.models',
    'apps.campaigns.models',
    'apps.campaigns.service',
    'apps.emails.service',
    'apps.tracking.models',
    'apps.tracking.views',
    'apps.tracking.tokens',
    'apps.tracking.signals',
    'apps.audit.models',
    'apps.admin_mixins',
]

out_dir = Path(__file__).resolve().parent.parent / 'docs'
pdoc.pdoc(*modules, output_directory=out_dir)
print('Docs generated in ../docs/')
