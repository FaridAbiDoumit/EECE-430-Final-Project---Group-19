from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('sessions/new/', views.create_session, name='create_session'),
    path('sessions/next/', views.next_session, name='next_session'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),
    path('coach/rsvps/', views.coach_rsvp_overview, name='coach_rsvp_overview'),
]
