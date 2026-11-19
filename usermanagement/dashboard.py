from collections import defaultdict
from django.contrib import admin
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate, login, logout
from usermanagement.encryption_util import *
from usermanagement.decorators import group_required
from django.contrib import admin
from .models import *
from django.db.models import Case, When, Value, CharField, Q,Count
from workspace.models import *
from workspace.helpers import *
from workspace.admin import compute_seat_type_stats, compute_emp_type_stats, compute_room_type_stats
import math
from django.db.models import Count


@login_required
def dashboard(request):
    from workspace.booking_workflow import role
    if role(request.user) in ('TEACHER', 'HOD', 'HOI'):
        return redirect('classroom_requests')
    template = ''
    context = {}
    if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['ADMIN', 'HOD', 'HOI'], is_active=1).exists():
        # ── Basic counts ──
        total_campuses = Campus.objects.filter(is_active=True).count()
        total_buildings = Building.objects.filter(is_active=True).count()
        total_blocks = Block.objects.filter(is_active=True).count()
        total_floors = Floor.objects.filter(is_active=True).count()
        total_rooms = Room.objects.filter(is_active=True).count()
        total_seats = Seat.objects.filter(is_active=True).count()

        # ── Seat status counts (occupied = seats with an active assignment) ──
        _occ_ids = set(SeatAllocationHistory.objects.filter(is_active=True, seat_status_id=2).values_list('seat_id', flat=True))
        available_seats = Seat.objects.filter(is_active=True, seat_status_id=1).count()
        occupied_seats  = Seat.objects.filter(is_active=True, id__in=_occ_ids).count()
        reserved_seats  = Seat.objects.filter(is_active=True, seat_status_id=3).count()
        maintenance_seats = Seat.objects.filter(is_active=True, seat_status_id=4).count()

        # ── Ring chart (circumference = 2πr ≈ 314) ──
        circ = 314

        def pct(val):
            return round((val / total_seats) * circ, 1) if total_seats > 0 else 0

        available_pct = pct(available_seats)
        occupied_pct = pct(occupied_seats)
        reserved_pct = pct(reserved_seats)
        remaining_pct = circ - available_pct
        occ_remaining = circ - occupied_pct
        res_remaining = circ - reserved_pct
        occupied_offset = -(available_pct)
        reserved_offset = -(available_pct + occupied_pct)

        # ── Seat type breakdown ──
        allocated_seat_ids = set(
            SeatAllocationHistory.objects.filter(is_active=True, seat_status_id=2).values_list('seat_id', flat=True)
        )
        seat_type_counts = []
        for st in SeatType.objects.filter(is_active=True):
            st_seats = Seat.objects.filter(seat_type=st, is_active=True)
            total = st_seats.count()
            occ = st_seats.filter(id__in=allocated_seat_ids).count()
            res = st_seats.filter(seat_status_id=3).count()
            seat_type_counts.append({
                'name': st.name,
                'count': total,
                'available': max(total - occ - res, 0),
                'occupied': occ,
                'reserved': res,
            })

        # ── Utilization widgets (Seat Type / Employee Type / Room Type) — shared
        #    with the Space Utilization page so the dashboard shows the same donuts/chart ──
        util_seat_qs = Seat.objects.filter(is_active=True, room_id__is_active=1)
        seat_type_stats = compute_seat_type_stats(util_seat_qs)
        emp_type_stats = compute_emp_type_stats(util_seat_qs)
        room_type_stats = compute_room_type_stats(util_seat_qs)
        util_buildings = Building.objects.filter(is_active=True).order_by('name')
        util_rooms_list = Room.objects.filter(is_active=True).select_related('building').order_by('building__name', 'room_number')

        # ── Allocation counts (based on actual allocation records) ──
        active_allocs = SeatAllocationHistory.objects.filter(is_active=True)
        total_allocations = active_allocs.count()
        allocated_count = active_allocs.filter(seat_status_id=2).count()  # seat is Occupied
        reserved_allocations = active_allocs.filter(seat_status_id=3).count()  # seat is Reserved
        released_allocations = active_allocs.filter(seat_status_id=4).count()

        # ── Campus overview ──
        campus_overview = []
        for campus in Campus.objects.filter(is_active=True):
            buildings = Building.objects.filter(campus=campus, is_active=True).count()
            seats = Seat.objects.filter(room__campus=campus, is_active=True)
            campus_overview.append({
                'name': campus.name,
                'buildings': buildings,
                'seats': seats.count(),
                'available': seats.filter(seat_status_id=1).count(),
                'occupied': seats.filter(id__in=allocated_seat_ids).count(),
            })

        # ── Recent allocations ──
        recent_allocations = SeatAllocationHistory.objects.filter(
            is_active=True
        ).select_related(
            'seat', 'seat__room', 'seat__room__building', 'seat__room__campus',
            'seat_status', 'createdby'
        ).order_by('-created_at')[:10]
        context = {
            'total_campuses': total_campuses,
            'total_buildings': total_buildings,
            'total_blocks': total_blocks,
            'total_floors': total_floors,
            'total_rooms': total_rooms,
            'total_seats': total_seats,
            'available_seats': available_seats,
            'occupied_seats': occupied_seats,
            'reserved_seats': reserved_seats,
            'maintenance_seats': maintenance_seats,
            'available_pct': available_pct,
            'remaining_pct': remaining_pct,
            'occupied_pct': occupied_pct,
            'occ_remaining': occ_remaining,
            'reserved_pct': reserved_pct,
            'res_remaining': res_remaining,
            'occupied_offset': occupied_offset,
            'reserved_offset': reserved_offset,
            'seat_type_counts': seat_type_counts,
            'seat_type_stats': seat_type_stats,
            'emp_type_stats': emp_type_stats,
            'room_type_stats': room_type_stats,
            'buildings': util_buildings,
            'rooms_list': util_rooms_list,
            'total_allocations': total_allocations,
            'allocated_count': allocated_count,
            'reserved_allocations': reserved_allocations,
            'released_allocations': released_allocations,
            'campus_overview': campus_overview,
            'recent_allocations': recent_allocations,
        }
        template = 'dashboard/admin.html'
    elif UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
        # ── Basic counts ──
        user_id=request.user.id
        total_campuses = Campus.objects.filter(is_active=True,id__in=get_access_campus(user_id)).count()
        total_buildings = Building.objects.filter(is_active=True,id__in=get_access_building(user_id)).count()
        total_blocks = Block.objects.filter(is_active=True,id__in=get_access_block(user_id)).count()
        total_floors = Floor.objects.filter(is_active=True,id__in=get_access_floor(user_id)).count()
        total_rooms = Room.objects.filter(is_active=True,id__in=get_access_rooms(user_id)).count()
        total_seats = Seat.objects.filter(is_active=True,id__in=get_access_seats(user_id)).count()

        # ── Seat status counts (occupied = seats with an active assignment) ──
        _access = get_access_seats(user_id)
        _occ_ids = set(SeatAllocationHistory.objects.filter(is_active=True, seat_status_id=2, seat_id__in=_access).values_list('seat_id', flat=True))
        available_seats   = Seat.objects.filter(is_active=True, seat_status_id=1, id__in=_access).count()
        occupied_seats    = Seat.objects.filter(is_active=True, id__in=_occ_ids).count()
        reserved_seats    = Seat.objects.filter(is_active=True, seat_status_id=3, id__in=_access).count()
        maintenance_seats = Seat.objects.filter(is_active=True, seat_status_id=4, id__in=_access).count()

        # ── Ring chart (circumference = 2πr ≈ 314) ──
        circ = 314

        def pct(val):
            return round((val / total_seats) * circ, 1) if total_seats > 0 else 0

        available_pct = pct(available_seats)
        occupied_pct = pct(occupied_seats)
        reserved_pct = pct(reserved_seats)
        remaining_pct = circ - available_pct
        occ_remaining = circ - occupied_pct
        res_remaining = circ - reserved_pct
        occupied_offset = -(available_pct)
        reserved_offset = -(available_pct + occupied_pct)

        # ── Seat type breakdown ──
        allocated_seat_ids = set(
            SeatAllocationHistory.objects.filter(is_active=True, seat_status_id=2, seat_id__in=get_access_seats(user_id)).values_list('seat_id', flat=True)
        )
        seat_type_counts = []
        for st in SeatType.objects.filter(is_active=True):
            st_seats = Seat.objects.filter(seat_type=st, is_active=True,id__in=get_access_seats(user_id))
            total = st_seats.count()
            occ = st_seats.filter(id__in=allocated_seat_ids).count()
            res = st_seats.filter(seat_status_id=3).count()
            seat_type_counts.append({
                'name': st.name,
                'count': total,
                'available': max(total - occ - res, 0),
                'occupied': occ,
                'reserved': res,
            })

        # ── Utilization widgets (Seat Type / Employee Type / Room Type) — shared
        #    with the Space Utilization page so the dashboard shows the same donuts/chart ──
        util_seat_qs = Seat.objects.filter(is_active=True, room_id__is_active=1, id__in=get_access_seats(user_id))
        seat_type_stats = compute_seat_type_stats(util_seat_qs)
        emp_type_stats = compute_emp_type_stats(util_seat_qs)
        room_type_stats = compute_room_type_stats(util_seat_qs)
        util_buildings = Building.objects.filter(is_active=True, id__in=get_access_building(user_id)).order_by('name')
        util_rooms_list = Room.objects.filter(is_active=True, id__in=get_access_rooms(user_id)).select_related('building').order_by('building__name', 'room_number')

        # ── Allocation counts (based on actual allocation records) ──
        active_allocs = SeatAllocationHistory.objects.filter(is_active=True,seat_id__in=get_access_seats(user_id))
        total_allocations = active_allocs.count()
        allocated_count = active_allocs.filter(seat_status_id=2).count()
        reserved_allocations = active_allocs.filter(seat_status_id=3).count()
        released_allocations = active_allocs.filter(seat_status_id=4).count()

        # ── Campus overview ──
        campus_overview = []
        for campus in Campus.objects.filter(is_active=True,id__in=get_access_campus(user_id)):
            buildings = Building.objects.filter(campus=campus, is_active=True,id__in=get_access_building(user_id)).count()
            seats = Seat.objects.filter(room__campus=campus, is_active=True,id__in=get_access_seats(user_id))
            campus_overview.append({
                'name': campus.name,
                'buildings': buildings,
                'seats': seats.count(),
                'available': seats.filter(seat_status_id=1).count(),
                'occupied': seats.filter(id__in=allocated_seat_ids).count(),
            })

        # ── Recent allocations ──
        recent_allocations = SeatAllocationHistory.objects.filter(
            is_active=True,seat_id__in=get_access_seats(user_id)
        ).select_related(
            'seat', 'seat__room', 'seat__room__building', 'seat__room__campus',
            'seat_status', 'createdby'
        ).order_by('-created_at')[:10]


        template = 'dashboard/radmin.html'

        context = {
            'total_campuses': total_campuses,
            'total_buildings': total_buildings,
            'total_blocks': total_blocks,
            'total_floors': total_floors,
            'total_rooms': total_rooms,
            'total_seats': total_seats,
            'available_seats': available_seats,
            'occupied_seats': occupied_seats,
            'reserved_seats': reserved_seats,
            'maintenance_seats': maintenance_seats,
            'available_pct': available_pct,
            'remaining_pct': remaining_pct,
            'occupied_pct': occupied_pct,
            'occ_remaining': occ_remaining,
            'reserved_pct': reserved_pct,
            'res_remaining': res_remaining,
            'occupied_offset': occupied_offset,
            'reserved_offset': reserved_offset,
            'seat_type_counts': seat_type_counts,
            'seat_type_stats': seat_type_stats,
            'emp_type_stats': emp_type_stats,
            'room_type_stats': room_type_stats,
            'buildings': util_buildings,
            'rooms_list': util_rooms_list,
            'total_allocations': total_allocations,
            'allocated_count': allocated_count,
            'reserved_allocations': reserved_allocations,
            'released_allocations': released_allocations,
            'campus_overview': campus_overview,
            'recent_allocations': recent_allocations,
        }
        template = 'dashboard/radmin.html'
    if not template:
        template = 'dashboard/admin.html'
    return render(request, template, context)