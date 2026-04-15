from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class InactiveProfileLogoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            profile = getattr(request.user, 'player_profile', None)
            if profile is not None and (not profile.is_active or not request.user.is_active):
                logout(request)
                messages.error(request, 'This account has been deactivated. Please contact an admin.')
                if request.path != reverse('scheduling:login'):
                    return redirect('scheduling:login')

        return self.get_response(request)
