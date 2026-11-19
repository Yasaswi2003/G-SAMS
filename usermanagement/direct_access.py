"""Optional loopback-only development access using a designated existing account."""
import re
from ipaddress import ip_address
from urllib.parse import urlsplit
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.http import HttpResponse
from django.shortcuts import redirect


class LocalDirectAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        employee_link = re.fullmatch(r'/(?:user/)?ulogin/([^/]+)/?', request.path_info)
        if ((request.user.is_authenticated and not employee_link) or not settings.DEBUG
                or not getattr(settings, 'LOCAL_DIRECT_ACCESS', False)
                or request.method not in ('GET', 'HEAD')):
            return self.get_response(request)
        try:
            peer = ip_address(request.META.get('REMOTE_ADDR', ''))
            host = urlsplit('http://' + request.get_host()).hostname
        except ValueError:
            return self.get_response(request)
        # Never trust forwarded headers to activate direct access.
        if not peer.is_loopback or host not in ('localhost', '127.0.0.1', '::1'):
            return self.get_response(request)
        from .models import UserGroups
        from workspace.booking_workflow import role
        username = employee_link.group(1) if employee_link else getattr(settings, 'LOCAL_DIRECT_ACCESS_USERNAME', '')
        user = get_user_model().objects.filter(username=username, is_active=True,
                                               must_change_password=False).first()
        if (user is None or not role(user) or not UserGroups.objects.filter(
                user=user, is_active=True, is_block=False).exists()):
            if employee_link:
                return HttpResponse('This employee account is unavailable for local direct access.', status=404)
            return HttpResponse('Local direct access account is unavailable. Check LOCAL_DIRECT_ACCESS_USERNAME or disable local direct access.', status=503)
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        if employee_link:
            return redirect('dashboard')
        return self.get_response(request)
