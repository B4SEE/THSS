from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView
from .views import debug_toggle

admin.site.site_header = 'Phishing Simulation Platform'
admin.site.site_title  = 'Phishing Admin'
admin.site.index_title = 'Campaign Management'
admin.site.site_url    = None  # removes the "View site" link (no public-facing site)

urlpatterns = [
    # Redirect bare /admin/ to the campaign list — that is the effective home page
    re_path(r'^admin/$', RedirectView.as_view(url='/admin/campaigns/campaign/', permanent=False)),
    path('admin/settings/debug/', debug_toggle, name='debug_toggle'),
    path('admin/', admin.site.urls),
    path('', include('apps.tracking.urls')),
]
