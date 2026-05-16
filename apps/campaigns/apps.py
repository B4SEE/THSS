import os
import sys

from django.apps import AppConfig


class CampaignsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.campaigns'
    label = 'campaigns'

    def ready(self):
        # Start scheduler only in the web server process, not during management
        # commands like migrate or makemigrations.
        # RUN_MAIN=true  → Django autoreloader child process
        # --noreload     → runserver without autoreloader
        # daphne/uvicorn → ASGI server invoked directly
        argv = sys.argv
        in_server = (
            os.environ.get('RUN_MAIN') == 'true'
            or '--noreload' in argv
            or any(s in (argv[0] if argv else '') for s in ('daphne', 'uvicorn', 'gunicorn'))
        )
        if in_server:
            from .scheduler import start_scheduler
            start_scheduler()
