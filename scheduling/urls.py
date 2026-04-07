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
    path('sessions/<int:session_id>/plan/', views.edit_session_plan, name='edit_session_plan'),
    path('sessions/<int:session_id>/personal-note/', views.personal_note, name='personal_note'),
    path('notifications/', views.notification_inbox, name='notification_inbox'),
    path('notifications/<int:notification_id>/delete/', views.delete_notification, name='delete_notification'),
    path('coach/rsvps/', views.coach_rsvp_overview, name='coach_rsvp_overview'),
]
