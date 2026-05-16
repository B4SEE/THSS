from django.apps import AppConfig


class TrackingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.tracking'
    label = 'tracking'

    def ready(self):
        import apps.tracking.signals  # noqa: F401 — connects post_save → Redis broadcast
