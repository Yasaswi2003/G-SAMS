import sys
import clr
from django.conf import settings
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from django.shortcuts import redirect
from django.contrib.auth import login,authenticate,logout
from django.contrib import messages
from .models import *
from django.shortcuts import render
from django.http import HttpResponse
#sys.path.append(r"D:\Projects\Admissions")
#clr.AddReference("ClassLibrary1")
#from testDLLApp import Class1


def get_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ipaddress = x_forwarded_for.split(',')[-1].strip()
    else:
        ipaddress = request.META.get('REMOTE_ADDR')
    return ipaddress


def login_auth(request):
    try:
        enc_url = request.GET.get('id')
        if not enc_url:
            return redirect('/user/not_found')

        url = Class1.Decrypt(enc_url, True, settings.LEGACY_DECRYPT_KEY)
        empl_id = url.split("#")[0]

    except Exception as e:
        ErrorLogs.objects.create(log='decrypt_error', info=str(e))
        return redirect('/user/not_found')

    # --- Get User (Single Query) ---
    user = User.objects.filter(username=empl_id).first()
    if not user:
        ErrorLogs.objects.create(log='invalid_user', info=url)
        return redirect('/user/not_found')

    # --- Login ---
    user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, user)

    # --- Device Info ---
    ua = getattr(request, 'user_agent', None)
    device_type = (
        'Mobile' if ua and ua.is_mobile else
        'Tablet' if ua and ua.is_tablet else
        'PC'
    )

    browser_family = ua.browser.family if ua else request.META.get(
        'HTTP_USER_AGENT', 'Unknown'
    )
    browser_version = ua.browser.version_string if ua else ''
    os_family = ua.os.family if ua else 'Unknown'
    os_version = ua.os.version_string if ua else ''

    # --- Log User Session ---
    UserAuthLogs.objects.create(
        user=user,
        login_time=datetime.now(),
        ip_address=get_ip(request),
        session_key=request.session.session_key,
        login_data=url,
        device_type=device_type,
        browser=browser_family,
        browser_version=browser_version,
        os=os_family,
        os_version=os_version
    )

    return redirect('/workspace/space_utilization')


def url_encode(request,empid):
    enc_url_data = (
        empid
    )
    try:
        encrypted_url = Class1.Encrypt(enc_url_data, True, settings.LEGACY_DECRYPT_KEY)
        return HttpResponse(encrypted_url)
    except Exception as e:
        return HttpResponse("Encryption Failed", status=500)



