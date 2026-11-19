from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from usermanagement.models import *
from usermanagement.encryption_util import *
from datetime import datetime
from django.contrib.auth import authenticate, login as auth_login,logout
from django.contrib.auth.models import Group
from django.db.models import Count
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib import messages
from usermanagement.utils import *
from django.db.models import Case, When, IntegerField, Sum
from django.http import JsonResponse
from collections import defaultdict
from .dashboard import *
from .decorators import *
from django.db import transaction
from django.utils.http import url_has_allowed_host_and_scheme
def get_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ipaddress = x_forwarded_for.split(',')[-1].strip()
    else:
        ipaddress = request.META.get('REMOTE_ADDR')
    return ipaddress



def userlogout(request):
    UserAuthLogs.objects.filter(user_id=request.user.id, session_key=request.session.session_key).update(logout_time=datetime.now())
    logout(request)
    return redirect('/')


@login_required
def switch_role(request, group_id):
    target = request.GET.get('next', '')
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = '/dashboard'
    decoded_id = decrypt(group_id)
    if not decoded_id or not str(decoded_id).isdigit():
        messages.error(request, "Invalid role selection")
        return redirect(target)
    with transaction.atomic():
        roles = UserGroups.objects.select_for_update().filter(user_id=request.user.id)
        selected = roles.filter(group_id=int(decoded_id), is_block=False).first()
        if selected is None:
            messages.error(request, "You don't have Permission to access this role")
        else:
            roles.update(is_active=False)
            roles.filter(pk=selected.pk).update(is_active=True)
    return redirect(target)


def not_found(request):
    return HttpResponse('Page not found')

def ulogin(request,emp_id):
    # Compatibility for direct imports; the URL uses the same password-authenticated view.
    from .password_access import EmployeeLoginView
    return EmployeeLoginView.as_view()(request, emp_id=emp_id)
