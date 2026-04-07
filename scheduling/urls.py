from django.urls import path

from . import views

app_name = 'scheduling'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('sessions/new/', views.create_session, name='create_session'),
    path('sessions/next/', views.next_session, name='next_session'),
    path('sessions/<int:session_id>/', views.session_detail, name='session_detail'),
    path('sessions/<int:session_id>/edit/', views.edit_session, name='edit_session'),
    path('sessions/<int:session_id>/cancel/', views.cancel_session, name='cancel_session'),
    path('availability/new/', views.submit_availability, name='submit_availability'),
    path('availability/<int:availability_id>/', views.availability_detail, name='availability_detail'),
    path('coach/availability/', views.coach_availability_overview, name='coach_availability_overview'),
    path('polls/new/', views.create_vote_poll, name='create_vote_poll'),
    path('polls/<int:poll_id>/', views.vote_poll_detail, name='vote_poll_detail'),
    path('coach/rsvps/', views.coach_rsvp_overview, name='coach_rsvp_overview'),
]
