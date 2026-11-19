from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from .models import *
from usermanagement.decorators import *

def get_access_rooms(user_id):
    return list(
        EmployeeAccessPermission.objects.filter(
            user_id=user_id,
            is_active=1,
            room__isnull=False
        ).values_list('room_id', flat=True)
    )

def get_access_campus(user_id):
    room_ids = get_access_rooms(user_id)
    if not room_ids:
        return []
    return list(
        Room.objects.filter(
            id__in=room_ids,
            is_active=1
        ).values_list('campus_id', flat=True).distinct()
    )

def get_access_building(user_id):
    room_ids = get_access_rooms(user_id)
    if not room_ids:
        return []
    return list(
        Room.objects.filter(
            id__in=room_ids,
            is_active=1
        ).values_list('building_id', flat=True).distinct()
    )

def get_access_floor(user_id):
    room_ids = get_access_rooms(user_id)
    if not room_ids:
        return []
    return list(
        Room.objects.filter(
            id__in=room_ids
        ).values_list('floor_id', flat=True).distinct()
    )

def get_access_block(user_id):
    room_ids = get_access_rooms(user_id)
    if not room_ids:
        return []
    return list(
        Room.objects.filter(
            id__in=room_ids
        ).values_list('block_id', flat=True).distinct()
    )

def get_access_seats(user_id):
    room_ids = get_access_rooms(user_id)
    if not room_ids:
        return []
    seats = Seat.objects.filter(
        room_id__in=room_ids,
        is_active=True
    ).values_list('id', flat=True).distinct()
    return list(
        seats
    )