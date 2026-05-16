from django.urls import path
from . import views

app_name = 'tracking'

urlpatterns = [
    path('t/<str:name>/<str:token>/logo.gif',  views.pixel,    name='pixel'),
    path('t/<str:name>/<str:token>/',          views.landing,  name='landing'),
    path('t/<str:name>/<str:token>/submit/',   views.submit,   name='submit'),
    path('t/<str:name>/<str:token>/mfa/',      views.mfa,      name='mfa'),
    path('t/<str:name>/<str:token>/feedback/', views.feedback, name='feedback'),
    path('t/<str:name>/<str:token>/report/',   views.report,   name='report'),
]
