from functools import wraps
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from usermanagement.models import *
from usermanagement.encryption_util import *
from django.contrib import messages
from workspace.helpers import get_access_rooms
from workspace.models import *

def group_required(*group_names):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user
            if user.is_authenticated and user.is_active:
                if UserGroups.objects.filter(
                    user_id=user.id,
                    group__name__in=group_names,
                    is_active=1
                ).exists():
                    return view_func(request, *args, **kwargs)
            messages.error(request,'Permission Denied')
            return redirect('/dashboard')
        return _wrapped_view
    return decorator


def workspace_permission_required(view_func):

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):

        user = request.user

        # Apply only for RADMIN users
        if UserGroups.objects.filter(
                user_id=user.id,
                group__name__in=['RADMIN'],
                is_active=1
        ).exists():

            mapped_rooms = get_access_rooms(user.id)

            # No permission mapped
            if not mapped_rooms:
                messages.error(request,'Permission Denied')

            # Allowed hierarchy from rooms
            allowed_rooms = mapped_rooms

            allowed_campuses = list(
                Room.objects.filter(id__in=mapped_rooms)
                .values_list('campus_id', flat=True)
                .distinct()
            )

            allowed_blocks = list(
                Room.objects.filter(id__in=mapped_rooms)
                .values_list('block_id', flat=True)
                .distinct()
            )

            allowed_floors = list(
                Room.objects.filter(id__in=mapped_rooms)
                .values_list('floor_id', flat=True)
                .distinct()
            )

            # URL params
            campus = request.GET.get('campus')
            block = request.GET.get('block')
            floor = request.GET.get('floor')
            room = request.GET.get('room')

            # ---- VALIDATIONS ----

            if campus and int(campus) not in allowed_campuses:
                messages.error(request,'Permission Denied')

            if block and int(block) not in allowed_blocks:
                messages.error(request,'Permission Denied')

            if floor and int(floor) not in allowed_floors:
                messages.error(request,'Permission Denied')

            if room and int(room) not in allowed_rooms:
                messages.error(request,'Permission Denied')

            # attach allowed rooms to request (VERY USEFUL)
            request.allowed_rooms = allowed_rooms

        return view_func(request, *args, **kwargs)

    return _wrapped_view