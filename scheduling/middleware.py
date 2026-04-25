from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

_PENDING_EXEMPT_PREFIXES = None


def _pending_exempt(path):
    global _PENDING_EXEMPT_PREFIXES
    if _PENDING_EXEMPT_PREFIXES is None:
        _PENDING_EXEMPT_PREFIXES = (
            reverse('scheduling:pending_approval'),
            reverse('scheduling:logout'),
            reverse('scheduling:login'),
        )
    return path.startswith(_PENDING_EXEMPT_PREFIXES)


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
            elif profile is not None and not profile.is_approved:
                if not _pending_exempt(request.path):
                    return redirect('scheduling:pending_approval')
            elif request.user.is_staff:
                assignment = getattr(request.user, 'staff_team_assignment', None)
                if assignment is not None and not assignment.is_approved:
                    if not _pending_exempt(request.path):
                        return redirect('scheduling:pending_approval')

        return self.get_response(request)
