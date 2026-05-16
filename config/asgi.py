import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()

# WebSocket URL routing will be added here when the frontend is built
application = ProtocolTypeRouter({
    'http': django_asgi_app,
})
