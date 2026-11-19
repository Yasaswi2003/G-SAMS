from logging import exception

from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
from usermanagement.decorators import *
from usermanagement.utils import send_html_mail
from .models import *
from usermanagement.models import *
from .helpers import *
from django.http import JsonResponse
@login_required
@group_required('ADMIN')
@csrf_exempt
def building(request):
    # ---------- SAVE BUILDING ----------
    if request.method == "POST":
        name = request.POST.get('name').strip()
        code = request.POST.get('code')
        campus = request.POST.get('campus')
        total_floors = request.POST.get('total_floors')
        status = request.POST.get('is_active')
        building_status = request.POST.get('is_active')
        # duplicate check
        if Building.objects.filter(name=name, campus_id=campus).exists():
            return JsonResponse({
                "status": 300,
                "message": "Building already exists in this campus"
            })
        Building.objects.create(
            name=name,
            code=code,
            campus_id=campus,
            total_floors=total_floors,
            building_status_id=building_status,
            is_active=status,
            createdby=request.user
        )
        return JsonResponse({
            "status": 200,
            "message": "Building saved successfully"
        })
    # ---------- PREVIEW / LIST ----------
    buildings = Building.objects.filter(is_active=1)
    building_status = BuildingStatus.objects.filter(is_active=True)
    campuses=Campus.objects.filter(is_active=1).all()
    context = {
        "buildings": buildings,
        "building_status": building_status,
        "campuses":campuses ,
        "total_buildings": buildings.count(),
        "active_buildings": buildings.filter(building_status_id=1).count(),
        "inactive_buildings": buildings.filter(building_status_id=2).count(),
        "renovation": buildings.filter(building_status_id=3).count()
    }
    return render(request, "workspace/building.html", context)

@login_required
@group_required('ADMIN')
@csrf_exempt
def block(request):
    campuses = Campus.objects.filter(is_active=True)
    block_types = BlockType.objects.filter(is_active=True)
    blocks = Block.objects.filter(is_active=True)
    if request.method == "POST":
        name = request.POST.get("name")
        code = request.POST.get("code")
        campus_id = request.POST.get("campus")
        building_id = request.POST.get("building")
        block_type_id = request.POST.get("block_type")
        block_id = request.POST.get("block_id")
        # ---------------- UPDATE ----------------
        if block_id:
            exists = Block.objects.filter(
                name__iexact=name,
                building_id=building_id,
                campus_id=campus_id,
                is_active=True
            ).exclude(id=block_id).exists()
            if exists:
                return JsonResponse({
                    "status": 300,
                    "message": "Block already exists for this building."
                })
            Block.objects.filter(id=block_id).update(
                name=name,
                code=code,
                campus_id=campus_id,
                building_id=building_id,
                block_type_id=block_type_id
            )
            return JsonResponse({
                "status": 200,
                "message": "Block updated successfully."
            })
        # ============CREATE BLOCK ----------------
        exists = Block.objects.filter(
            name__iexact=name,
            building_id=building_id,
            campus_id=campus_id,
            is_active=True
        ).exists()

        if exists:
            return JsonResponse({
                "status": 300,
                "message": "Block already exists for this building."
            })
        Block.objects.create(
            name=name,
            code=code,
            campus_id=campus_id,
            building_id=building_id,
            block_type_id=block_type_id,
            createdby=request.user
        )
        return JsonResponse({
            "status": 200,
            "message": "Block created successfully."
        })

    context = {
        "campuses": campuses,
        "block_types": block_types,
        "blocks": blocks,
        "total_blocks": blocks.count(),
        "wing_count": blocks.filter(block_type_id=1).count(),
        "tower_count": blocks.filter(block_type_id=2).count(),
        "annex_count": blocks.filter(block_type_id=3).count(),
        "block_count": blocks.filter(block_type_id=4).count(),
    }
    return render(request, "workspace/block.html", context)

@login_required
@group_required('ADMIN')
@csrf_exempt
def floor(request):
    campuses = Campus.objects.filter(is_active=True)
    floors   = Floor.objects.filter(is_active=True)
    if request.method == "POST":
        campus_id = request.POST.get('campus')
        building_id = request.POST.get('building')
        block_id = request.POST.get('block')
        floor_numbers = request.POST.getlist('floor_number')
        floor_labels = request.POST.getlist('floor_label')

        created_count = 0
        duplicate_count = 0

        for number, label in zip(floor_numbers, floor_labels):
            if not number or not label:
                continue

            exists = Floor.objects.filter(
                floor_number=number,
                block_id=block_id,
                building_id=building_id,
                campus_id=campus_id
            ).exists()

            if exists:
                duplicate_count += 1
                continue

            Floor.objects.create(
                floor_number=number,
                floor_label=label,
                campus_id=campus_id,
                building_id=building_id,
                block_id=block_id,
                createdby=request.user
            )
            created_count += 1

        if created_count > 0 and duplicate_count == 0:
            return JsonResponse({"status": 200, "message": f"{created_count} floor(s) saved successfully."})
        elif created_count > 0 and duplicate_count > 0:
            return JsonResponse(
                {"status": 200, "message": f"{created_count} floor(s) saved. {duplicate_count} duplicate(s) skipped."})
        else:
            return JsonResponse({"status": 300, "message": "All floors already exist for this block."})
    context = {
        "campuses" : campuses,
        "floors"   : floors,
    }
    return render(request, 'workspace/floor.html', context)

@login_required
@group_required('ADMIN')
@csrf_exempt
def room(request):
    campuses = Campus.objects.filter(is_active=True)
    room_types = RoomType.objects.filter(is_active=True)
    rooms = Room.objects.all().select_related('room_type', 'floor', 'block', 'building', 'campus', 'createdby')
    filter_buildings = Building.objects.filter(id__in=rooms.values_list('building_id', flat=True)).order_by('name')
    filter_room_names = rooms.exclude(room_number='').values_list('room_number', flat=True).distinct().order_by('room_number')

    if request.method == "POST":

        campus_id = request.POST.get("campus")
        building_id = request.POST.get("building")
        block_id = request.POST.get("block")
        floor_id = request.POST.get("floor")
        room_type_id = request.POST.get("room_type")
        room_number = request.POST.get("room_number")
        room_name = request.POST.get("room_name", "").strip()
        room_id = request.POST.get("room_id")

        # ---------------- UPDATE ----------------
        if room_id:

            exists = Room.objects.filter(
                room_number__iexact=room_number,
                floor_id=floor_id,
                block_id=block_id,
                building_id=building_id,
                campus_id=campus_id,
                is_active=True
            ).exclude(id=room_id).exists()

            if exists:
                return JsonResponse({
                    "status": 300,
                    "message": "Room already exists on this floor."
                })

            Room.objects.filter(id=room_id).update(
                campus_id=campus_id,
                building_id=building_id,
                block_id=block_id,
                floor_id=floor_id,
                room_type_id=room_type_id,
                room_number=room_number,
                room_name=room_name
            )

            return JsonResponse({
                "status": 200,
                "message": "Room updated successfully."
            })

        # ---------------- CREATE ----------------
        exists = Room.objects.filter(
            room_number__iexact=room_number,
            floor_id=floor_id,
            block_id=block_id,
            building_id=building_id,
            campus_id=campus_id,
            is_active=True
        ).exists()

        if exists:
            return JsonResponse({
                "status": 300,
                "message": "Room already exists on this floor."
            })

        Room.objects.create(
            campus_id=campus_id,
            building_id=building_id,
            block_id=block_id,
            floor_id=floor_id,
            room_type_id=room_type_id,
            room_number=room_number,
            room_name=room_name,
            createdby=request.user
        )

        return JsonResponse({
            "status": 200,
            "message": "Room created successfully."
        })

    context = {
        "campuses": campuses,
        "room_types": room_types,
        "rooms": rooms,
        "filter_buildings": filter_buildings,
        "filter_room_names": filter_room_names,
        "all_room_types": RoomType.objects.all().order_by('name'),
    }

    return render(request, "workspace/room.html", context)


@login_required
@group_required('ADMIN')
@csrf_exempt
def room_type_save(request):
    if request.method != "POST":
        return JsonResponse({"status": 0, "message": "Invalid request."})

    room_type_id = request.POST.get("room_type_id")
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()

    if not name:
        return JsonResponse({"status": 300, "message": "Room type name is required."})

    if room_type_id:
        if RoomType.objects.filter(name__iexact=name).exclude(id=room_type_id).exists():
            return JsonResponse({"status": 300, "message": "Room type already exists."})
        RoomType.objects.filter(id=room_type_id).update(name=name, description=description)
        return JsonResponse({"status": 200, "message": "Room type updated successfully."})

    if RoomType.objects.filter(name__iexact=name).exists():
        return JsonResponse({"status": 300, "message": "Room type already exists."})
    RoomType.objects.create(name=name, description=description)
    return JsonResponse({"status": 200, "message": "Room type created successfully."})

@login_required
@group_required('ADMIN')
@csrf_exempt
def seat_type_save(request):
    if request.method != "POST":
        return JsonResponse({"status": 0, "message": "Invalid request."})

    seat_type_id = request.POST.get("seat_type_id")
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()

    if not name:
        return JsonResponse({"status": 300, "message": "Room type name is required."})

    if seat_type_id:
        if SeatType.objects.filter(name__iexact=name).exclude(id=seat_type_id).exists():
            return JsonResponse({"status": 300, "message": "Room type already exists."})
        SeatType.objects.filter(id=seat_type_id).update(name=name, description=description)
        return JsonResponse({"status": 200, "message": "Room type updated successfully."})

    if SeatType.objects.filter(name__iexact=name).exists():
        return JsonResponse({"status": 300, "message": "Room type already exists."})
    SeatType.objects.create(name=name, description=description)
    return JsonResponse({"status": 200, "message": "Room type created successfully."})
@login_required
@group_required('ADMIN')
def get_room_type_details(request):
    if request.method != "POST":
        return JsonResponse({"status": 0, "message": "Invalid request."})

    room_type_id = request.POST.get("room_type_id")
    try:
        rt = RoomType.objects.get(id=room_type_id)
        return JsonResponse({
            "status": 1,
            "data": {"id": rt.id, "name": rt.name, "description": rt.description or ""}
        })
    except RoomType.DoesNotExist:
        return JsonResponse({"status": 0, "message": "Room type not found."})

@login_required
@group_required('ADMIN')
def get_seat_type_details(request):
    if request.method != "POST":
        return JsonResponse({"status": 0, "message": "Invalid request."})

    seat_type_id = request.POST.get("seat_type_id")
    try:
        rt = SeatType.objects.get(id=seat_type_id)
        return JsonResponse({
            "status": 1,
            "data": {"id": rt.id, "name": rt.name, "description": rt.description or ""}
        })
    except SeatType.DoesNotExist:
        return JsonResponse({"status": 0, "message": "Room type not found."})

@login_required
@group_required('ADMIN','RADMIN')
@csrf_exempt
def seating(request):
    campuses = Campus.objects.filter(is_active=True)
    seat_types = SeatType.objects.filter(is_active=True)
    seat_statuses = SeatStatus.objects.filter(is_active=True, id__in=[1, 4])
    seats = Seat.objects.filter(is_active=True,room_id__is_active=1).select_related(
        'seat_type', 'seat_status',
        'room', 'room__floor', 'room__block', 'room__building', 'room__campus',
        'createdby'
    )
    if request.method == "POST":
        room_id = request.POST.get('room')
        seat_type_id = request.POST.get('seat_type')
        seat_prefix = request.POST.get('seat_prefix', '').strip()
        start_from = int(request.POST.get('start_from', 1))
        count = int(request.POST.get('count', 1))

        created_count = 0
        duplicate_count = 0

        for i in range(count):
            seat_number = f"{seat_prefix}{start_from + i}"
            exists = Seat.objects.filter(seat_number=seat_number, room_id=room_id).exists()
            if exists:
                duplicate_count += 1
                continue
            Seat.objects.create(
                seat_number=seat_number,
                room_id=room_id,
                seat_type_id=seat_type_id,
                seat_status_id=1,
                createdby=request.user
            )
            created_count += 1

        if created_count > 0 and duplicate_count == 0:
            return JsonResponse({"status": 200, "message": f"{created_count} seat(s) saved successfully."})
        elif created_count > 0 and duplicate_count > 0:
            return JsonResponse(
                {"status": 200, "message": f"{created_count} seat(s) saved. {duplicate_count} duplicate(s) skipped."})
        else:
            return JsonResponse({"status": 300, "message": "All seats already exist in this room."})
    if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
        mapped_campuses = get_access_campus(request.user.id)
        campuses = campuses.filter(id__in=mapped_campuses)
        mapped_rooms = get_access_rooms(request.user.id)
        seats = seats.filter(room_id__in=mapped_rooms)

    # ── Dashboard counts (before iterating) ──
    total_seats = seats.count()
    available_seats = seats.filter(seat_status_id=1).count()
    occupied_seats = seats.filter(seat_status_id=2).count()
    reserved_seats = seats.filter(seat_status_id=3).count()
    maintenance_seats = seats.filter(seat_status_id=4).count()

    # ── Bulk fetch employee details for all assigned seats ──
    emp_ids = [s.current_empid for s in seats if s.current_empid]
    emp_map = {}
    if emp_ids:
        for row in EmployeeMaster.objects.using('GITAM').filter(empid__in=emp_ids).values(
            'empid', 'emp_name', 'emailid', 'campus', 'college_code', 'dept_code', 'job_description'
        ):
            emp_map[str(row['empid'])] = {
                'name'       : row.get('emp_name') or '',
                'email'      : row.get('emailid') or '',
                'campus'     : row.get('campus') or '',
                'school'     : row.get('college_code') or '',
                'dept'       : row.get('dept_code') or '',
                'designation': row.get('job_description') or '',
                'source'     : 'Staff',
            }
        # Research faculty fallback for any empid not found in EmployeeMaster
        missing = [e for e in emp_ids if str(e) not in emp_map]
        if missing:
            for row in ResearchFaculty.objects.filter(emp_id__in=missing, is_active=True).values(
                'emp_id', 'name', 'email', 'college_code', 'dept_code', 'designation'
            ):
                emp_map[str(row['emp_id'])] = {
                    'name'       : row.get('name') or '',
                    'email'      : row.get('email') or '',
                    'campus'     : '',
                    'school'     : row.get('college_code') or '',
                    'dept'       : row.get('dept_code') or '',
                    'designation': row.get('designation') or 'Research Faculty',
                    'source'     : 'Research Faculty',
                }

        # Guest faculty fallback for any empid still not resolved
        missing = [e for e in emp_ids if str(e) not in emp_map]
        if missing:
            for row in GlearnGuestStaffMaster.objects.using('GITAM').filter(empid__in=missing).values(
                'empid', 'emp_name', 'emailid', 'campus', 'college_code', 'dept_code'
            ):
                emp_map[str(row['empid'])] = {
                    'name'       : row.get('emp_name') or '',
                    'email'      : row.get('emailid') or '',
                    'campus'     : row.get('campus') or '',
                    'school'     : row.get('college_code') or '',
                    'dept'       : row.get('dept_code') or '',
                    'designation': 'Guest Faculty',
                    'source'     : 'Guest Faculty',
                }

    for seat in seats:
        seat.assigned_to = seat.current_empid
        seat.emp_detail  = emp_map.get(str(seat.current_empid)) if seat.current_empid else None

    map_seat_statuses = SeatStatus.objects.filter(is_active=True)
    context = {
        "campuses": campuses,
        "seat_types": seat_types,
        "seat_statuses": seat_statuses,
        "seats": seats,
        "map_seat_statuses": map_seat_statuses,
        "total_seats": total_seats,
        "Available": available_seats,
        "Occupied": occupied_seats,
        "Reserved": reserved_seats,
        "Maintenance": maintenance_seats,
    }
    return render(request, 'workspace/seating.html', context)


@login_required
@group_required('ADMIN','RADMIN')
@csrf_exempt
def update_seat_status(request):
    if request.method != "POST":
        return JsonResponse({"status": 300, "message": 'invalid method'})
    seat_id   = request.POST.get('seat_id')
    status_id = int(request.POST.get('seat_status'))
    empid     = request.POST.get('empid', '').strip()
    remarks   = request.POST.get('remarks', '')

    try:
        seat = Seat.objects.get(id=seat_id, is_active=True)
    except Seat.DoesNotExist:
        return JsonResponse({"status": 300, "message": "Seat not found."})

    # Validate empid if Occupied
    if status_id == 2 and not empid:
        return JsonResponse({"status": 300, "message": "Employee ID is required for Occupied status."})

    # ── Validate: employee already allocated to another seat ──
    if status_id == 2:
        already_allocated = SeatAllocationHistory.objects.filter(
            empid     = empid,
            is_active = True,
            seat_status_id = 2,
        ).exclude(seat=seat).select_related('seat').first()

        if already_allocated:
            return JsonResponse({
                "status" : 300,
                "message": f"Employee {empid} is already allocated to Seat {already_allocated.seat.seat_number}. Please release it first."
            })

        # ── Validate: this seat is already occupied by a different employee ──
        if seat.seat_status_id == 2 and seat.current_empid and seat.current_empid != empid:
            return JsonResponse({
                "status" : 300,
                "message": f"Seat {seat.seat_number} is already occupied by {seat.current_empid}. Please release it before assigning a new employee."
            })

    # ── 1. Close old active history record ──
    SeatAllocationHistory.objects.filter(
        seat=seat,
        is_active=True
    ).update(
        is_active=False,
        released_date=datetime.now()
    )

    # ── 2. Update Seat ──
    seat.seat_status_id = status_id
    seat.current_empid  = empid if status_id == 2 else None
    seat.save()
    # ── Resolve employee details: EmployeeMaster -> ResearchFaculty -> GlearnGuestStaffMaster ──
    employee = None
    emp_row = EmployeeMaster.objects.using('GITAM').filter(empid=empid).values(
        'emp_name', 'emailid', 'campus', 'college_code', 'dept_code', 'job_description','empid'
    ).last()
    if emp_row:
        employee = {
            'emp_name'       : emp_row.get('emp_name'),
            'empid'          : emp_row.get('empid'),
            'emailid'        : emp_row.get('emailid'),
            'campus'         : emp_row.get('campus'),
            'college_code'   : emp_row.get('college_code'),
            'dept_code'      : emp_row.get('dept_code'),
            'job_description': emp_row.get('job_description'),
        }

    if not employee and empid:
        rf_row = ResearchFaculty.objects.filter(emp_id=empid, is_active=True).values(
            'name', 'email', 'college_code', 'dept_code', 'designation','emp_id'
        ).last()
        if rf_row:
            employee = {
                'emp_name'       : rf_row.get('name'),
                'emailid'        : rf_row.get('email'),
                'empid'        : rf_row.get('emp_id'),
                'campus'         : None,
                'college_code'   : rf_row.get('college_code'),
                'dept_code'      : rf_row.get('dept_code'),
                'job_description': rf_row.get('designation'),
            }

    if not employee and empid:
        gl_row = GlearnGuestStaffMaster.objects.using('GITAM').filter(empid=empid).values(
            'emp_name', 'emailid', 'campus', 'college_code', 'dept_code','empid'
        ).last()
        if gl_row:
            employee = {
                'emp_name'       : gl_row.get('emp_name'),
                'emailid'        : gl_row.get('emailid'),
                'empid'        : gl_row.get('empid'),
                'campus'         : gl_row.get('campus'),
                'college_code'   : gl_row.get('college_code'),
                'dept_code'      : gl_row.get('dept_code'),
                'job_description': 'Guest Faculty',
            }
    # ── 3. Create new history record ──
    SeatAllocationHistory.objects.create(
        seat=seat,
        empid=empid if empid else None,
        seat_status_id=status_id,
        remarks=remarks,
        createdby=request.user,
        campus = employee['campus'] if employee else None,
        college_code = employee['college_code'] if employee else None,
        dept_code = employee['dept_code'] if employee else None,
        designation = employee['job_description'] if employee else None,
    )

    # ── 4. Send email alert when Occupied ──
    if status_id == 2 :
        try:

            if employee:

                subject        = f'Seat Allocated — {seat.seat_number}'
                sender         = settings.EMAIL_HOST_USER
                recipient_list = [employee['emailid']]
                html_content   = render_to_string('workspace/seat_email_template.html', {
                    'employee_name' : employee['emp_name'],
                     'empid' : employee['empid'],
                    'seat_number'   : seat.seat_number,
                    'room'          : seat.room.room_number if seat.room else '—',
                    'floor'         : seat.room.floor.floor_label if seat.room and seat.room.floor else '—',
                    'building'      : seat.room.floor.block.building.name if seat.room and seat.room.floor and seat.room.floor.block else '—',
                    'campus'        : seat.room.floor.block.building.campus.name if seat.room and seat.room.floor and seat.room.floor.block else '—',
                    'allocated_on'  : datetime.now().strftime('%d %b %Y, %I:%M %p'),
                    'allocated_by'  : request.user.first_name,
                    'remarks'       : remarks or '—',
                })
                send_html_mail(subject, html_content, recipient_list, sender)

        except Exception as e:
            print(e)
            return JsonResponse({
                "status": 300,
                "message": str(e)
            })

    status_names = {1: 'Available', 2: 'Occupied', 3: 'Reserved', 4: 'Maintenance'}
    return JsonResponse({
        "status" : 200,
        "message": f"Seat {seat.seat_number} updated to {status_names.get(status_id, 'Unknown')}."
    })

#################################
@csrf_exempt
def get_buildings_by_campus(request):
    if request.method == "POST":
        campus_id = request.POST.get('campus_id')
        buildings = Building.objects.filter(
            campus_id=campus_id,
            is_active=True
        ).values('id', 'name','code')
        if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
            mapped_building = get_access_building(request.user.id)
            buildings = buildings.filter(id__in=mapped_building)

        return JsonResponse({
            'buildings': list(buildings)
        })
    else:
        return JsonResponse({})

@csrf_exempt
def get_blocks_by_building_campus(request):
    if request.method == "POST":
        campus_id = request.POST.get('campus_id')
        building_id = request.POST.get('building_id')
        block = Block.objects.filter(
            campus_id=campus_id,
            building_id=building_id,
            is_active=True
        ).values('id', 'name','code')
        if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
            mapped_block = get_access_block(request.user.id)
            block = block.filter(id__in=mapped_block)

        return JsonResponse({
            'block': list(block)
        })
    else:
        return JsonResponse({})


@csrf_exempt
def get_floors_by_block(request):
    if request.method == "POST":
        block_id    = request.POST.get('block_id')
        building_id = request.POST.get('building_id')
        floors = Floor.objects.filter(
            block_id=block_id,
            building_id=building_id,
            is_active=True
        ).values('id', 'floor_number', 'floor_label').order_by('floor_number')
        if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
            mapped_floors = get_access_floor(request.user.id)
            floors = floors.filter(id__in=mapped_floors)
        return JsonResponse({'floors': list(floors)})
    return JsonResponse({})

@csrf_exempt
def get_rooms_by_floor(request):
    if request.method == "POST":
        floor_id = request.POST.get('floor_id')
        rooms = Room.objects.filter(
            floor_id=floor_id,
            is_active=True
        ).values('id', 'room_number')
        if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
            mapped_rooms = get_access_rooms(request.user.id)
            rooms = rooms.filter(id__in=mapped_rooms)
        return JsonResponse({'rooms': list(rooms)})
    return JsonResponse({})

@csrf_exempt
def get_seats_by_room(request):
    if request.method == "POST":
        room_id = request.POST.get('room_id')
        seats = Seat.objects.filter(
            room_id=room_id,
            is_active=True
        ).values('id', 'seat_number')
        if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
            mapped_rooms = get_access_rooms(request.user.id)
            seats = seats.filter(room_id__in=mapped_rooms)
        return JsonResponse({'seats': list(seats)})
    return JsonResponse({})

import re

def natural_sort_key(seat):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', seat.seat_number)]


@login_required
@workspace_permission_required
@group_required('ADMIN','RADMIN')
def seat_layout(request):
    campuses = Campus.objects.filter(is_active=True)
    blocks = Block.objects.filter(is_active=True).select_related('building', 'campus')
    floors = Floor.objects.filter(is_active=True).select_related('block', 'building')
    rooms = Room.objects.filter(is_active=True).select_related('floor', 'block', 'building', 'campus')
    mapped_rooms = []
    if UserGroups.objects.filter(user_id=request.user.id, group__name__in=['RADMIN'], is_active=1).exists():
        mapped_campus = get_access_campus(request.user.id)
        mapped_block = get_access_block(request.user.id)
        mapped_floor = get_access_floor(request.user.id)
        mapped_rooms = get_access_rooms(request.user.id)
        campuses = campuses.filter(id__in=mapped_campus)
        blocks = blocks.filter(id__in=mapped_block)
        floors = floors.filter(id__in=mapped_floor)
        rooms = rooms.filter(id__in=mapped_rooms)

    selected_campus = request.GET.get('campus', '')
    selected_block = request.GET.get('block', '')
    selected_floor = request.GET.get('floor', '')
    selected_room = request.GET.get('room', '')

    if selected_campus:
        blocks = blocks.filter(campus_id=selected_campus)
        floors = floors.filter(campus_id=selected_campus)
        rooms = rooms.filter(campus_id=selected_campus)

    if selected_block:
        floors = floors.filter(block_id=selected_block)
        rooms = rooms.filter(block_id=selected_block)

    if selected_floor:
        rooms = rooms.filter(floor_id=selected_floor)

    # ── Build floor → seats data ──
    floor_qs = floors.filter(id=selected_floor) if selected_floor else floors

    floor_seat_data = []
    for floor in floor_qs.order_by('floor_number'):
        seats = Seat.objects.filter(
            room__floor=floor,
            is_active=True,room_id__is_active=1
        ).select_related('seat_status', 'seat_type', 'room',)

        if mapped_rooms:
            seats = seats.filter(room_id__in=mapped_rooms)

        if selected_block:
            seats = seats.filter(room__block_id=selected_block)
        if selected_room:
            seats = seats.filter(room_id=selected_room)

        emp_ids = list(seats.exclude(
            current_empid__isnull=True
        ).values_list('current_empid', flat=True).distinct())

        master_data = EmployeeMaster.objects.using('GITAM').filter(
            empid__in=emp_ids
        ).values(
            'empid', 'emp_name', 'campus', 'college_code', 'dept_code', 'gender'
        )
        emp_dict = {
            emp['empid']: emp for emp in master_data
        }
        # Group seats by room
        room_map = {}
        for s in seats:
            emp_info = emp_dict.get(s.current_empid)
            s.assigned_to = s.current_empid
            if emp_info:
                s.emp_name = emp_info['emp_name']
                s.gender = emp_info['gender']
                s.campus = emp_info['campus']
                s.college_code = emp_info['college_code']
                s.dept_code = emp_info['dept_code']
            room = s.room
            if room.id not in room_map:
                room_map[room.id] = {'room': room, 'seats': []}
            room_map[room.id]['seats'].append(s)

        # Natural sort seats within each room
        rooms_data = []
        for rd in room_map.values():
            rd['seats'] = sorted(rd['seats'], key=natural_sort_key)
            rooms_data.append(rd)

        # Sort rooms by room_number
        rooms_data.sort(
            key=lambda x: [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', x['room'].room_number)]
        )

        all_floor_seats = [s for rd in rooms_data for s in rd['seats']]
        available = sum(1 for s in all_floor_seats if s.seat_status_id == 1)
        occupied = sum(1 for s in all_floor_seats if s.seat_status_id == 2)
        reserved = sum(1 for s in all_floor_seats if s.seat_status_id == 3)
        maintenance = sum(1 for s in all_floor_seats if s.seat_status_id == 4)

        if all_floor_seats:
            floor_seat_data.append({
                'floor': floor,
                'rooms': rooms_data,
                'available': available,
                'occupied': occupied,
                'reserved': reserved,
                'maintenance': maintenance,
            })

    # ── Totals ──
    all_seats = [s for fd in floor_seat_data for rd in fd['rooms'] for s in rd['seats']]
    total_available = sum(1 for s in all_seats if s.seat_status_id == 1)
    total_occupied = sum(1 for s in all_seats if s.seat_status_id == 2)
    total_reserved = sum(1 for s in all_seats if s.seat_status_id == 3)
    total_maintenance = sum(1 for s in all_seats if s.seat_status_id == 4)

    selected_block_obj = None
    if selected_block:
        selected_block_obj = Block.objects.filter(
            id=selected_block
        ).select_related('building', 'campus').first()
    seat_statuses = SeatStatus.objects.filter(is_active=True)
    context = {
        'campuses': campuses,'seat_statuses':seat_statuses,
        'blocks': blocks,
        'floors': floors,
        'rooms': rooms,
        'floor_seat_data': floor_seat_data,
        'selected_campus': selected_campus,
        'selected_block': selected_block,
        'selected_floor': selected_floor,
        'selected_room': selected_room,
        'selected_block_obj': selected_block_obj,
        'total_available': total_available,
        'total_occupied': total_occupied,
        'total_reserved': total_reserved,
        'total_maintenance': total_maintenance,
    }
    return render(request, 'workspace/seat_layout_page.html', context)


@login_required
@csrf_exempt
def get_seat_history(request):
    if request.method != "POST":
        return JsonResponse({})

    seat_id = request.POST.get('seat_id')

    history = SeatAllocationHistory.objects.filter(
        seat_id=seat_id
    ).select_related('seat_status', 'createdby').order_by('-created_at')

    data = []
    for h in history:
        data.append({
            'empid'           : h.empid or '',
            'seat_status_id'  : h.seat_status_id,
            'seat_status_name': h.seat_status.name if h.seat_status else '',
            'allocated_date': h.allocated_date.strftime('%d-%m-%Y %H:%M:%S') if h.allocated_date else '',
            'released_date': h.released_date.strftime('%d-%m-%Y %H:%M:%S') if h.released_date else '',
            'remarks'         : h.remarks or '',
            'createdby'       : h.createdby.first_name if h.createdby else '',
        })

    return JsonResponse({'history': data})


def compute_room_type_stats(seat_qs):
    """Occupied/Available seat counts per room type (Office, Classroom, Laboratory, etc.)
    for whatever seat queryset is passed in — used both for the full-page load and the
    Building/Room-filtered AJAX refresh of the Room Type Utilization chart."""
    colors = ['#007367', '#2B7158', '#1d4ed8', '#5b21b6', '#92400e', '#166534', '#991b1b', '#475569']
    room_type_stats = []
    for i, rt in enumerate(RoomType.objects.filter(is_active=True)):
        rts = seat_qs.filter(room__room_type=rt)
        rt_total = rts.count()
        if rt_total == 0:
            continue
        rt_occ = rts.filter(seat_status_id=2).count()
        rt_avail = rts.filter(seat_status_id=1).count()
        rt_res = rts.filter(seat_status_id=3).count()
        rt_maint = rts.filter(seat_status_id=4).count()
        rt_pct = round(rt_occ / rt_total * 100) if rt_total > 0 else 0
        rt_avail_pct = round(rt_avail / rt_total * 100) if rt_total > 0 else 0
        rt_circ = 276
        rt_occ_dash = round(rt_pct / 100 * rt_circ, 1)
        rt_avail_dash = round(rt_avail_pct / 100 * rt_circ, 1)
        room_type_stats.append({
            'name': rt.name,
            'bg_color': colors[i % len(colors)],
            'total': rt_total,
            'occupied': rt_occ,
            'available': rt_avail,
            'reserved': rt_res,
            'maintenance': rt_maint,
            'pct': rt_pct,
            'occ_dash': rt_occ_dash,
            'occ_gap': rt_circ - rt_occ_dash,
            'avail_dash': rt_avail_dash,
            'avail_gap': rt_circ - rt_avail_dash,
        })

    # Bar-height scaling (floor of 4% keeps small non-zero bars visible/clickable
    # instead of collapsing to nothing)
    room_type_max = max([max(rt['available'], rt['occupied']) for rt in room_type_stats], default=1) or 1
    for rt in room_type_stats:
        rt['avail_bar_pct'] = max(round(rt['available'] / room_type_max * 100), 4) if rt['available'] > 0 else 0
        rt['occ_bar_pct'] = max(round(rt['occupied'] / room_type_max * 100), 4) if rt['occupied'] > 0 else 0

    return room_type_stats


def compute_seat_type_stats(seat_qs):
    """Per-seat-type donut data (Cubicle, Workstation, Director's Cabin, etc.) for
    whatever seat queryset is passed in — shared by the Space Utilization page and
    the dashboard."""
    colors = ['#007367', '#2B7158', '#1d4ed8', '#5b21b6', '#92400e', '#166534', '#991b1b', '#475569']
    seat_type_stats = []
    for i, st in enumerate(SeatType.objects.filter(is_active=True)):
        ts = seat_qs.filter(seat_type=st)
        t_total = ts.count()
        t_occ = ts.filter(seat_status_id=2).count()
        t_avail = ts.filter(seat_status_id=1).count()
        t_res = ts.filter(seat_status_id=3).count()
        t_maint = ts.filter(seat_status_id=4).count()
        t_pct = round(t_occ / t_total * 100) if t_total > 0 else 0
        avail_pct = round(t_avail / t_total * 100) if t_total > 0 else 0
        # SVG donut (r=44, circ≈276)
        circ = 276
        occ_dash = round(t_pct / 100 * circ, 1)
        avail_dash = round(avail_pct / 100 * circ, 1)
        seat_type_stats.append({
            'name': st.name,
            'icon': st.icon or 'bx bx-chair',
            'color': st.color or colors[i % len(colors)],
            'bg_color': colors[i % len(colors)],
            'total': t_total,
            'occupied': t_occ,
            'available': t_avail,
            'reserved': t_res,
            'maintenance': t_maint,
            'pct': t_pct,
            'avail_pct': avail_pct,
            'occ_dash': occ_dash,
            'occ_gap': circ - occ_dash,
            'avail_dash': avail_dash,
            'avail_gap': circ - avail_dash,
        })
    return seat_type_stats


def compute_emp_type_stats(seat_qs):
    """Donut data for occupied seats grouped by employee source (Staff / Research
    Faculty / Guest Faculty) — shared by the Space Utilization page and the dashboard."""
    occupied_empids = list(
        seat_qs.filter(seat_status_id=2).exclude(current_empid__isnull=True).exclude(current_empid='')
        .values_list('current_empid', flat=True)
    )
    staff_set = set(str(e) for e in EmployeeMaster.objects.using('GITAM').filter(empid__in=occupied_empids).values_list('empid', flat=True))
    remaining_ids = [e for e in occupied_empids if str(e) not in staff_set]
    research_set = set(str(e) for e in ResearchFaculty.objects.filter(emp_id__in=remaining_ids, is_active=True).values_list('emp_id', flat=True))
    remaining_ids2 = [e for e in remaining_ids if str(e) not in research_set]
    guest_set = set(str(e) for e in GlearnGuestStaffMaster.objects.using('GITAM').filter(empid__in=remaining_ids2).values_list('empid', flat=True))

    staff_count = sum(1 for e in occupied_empids if str(e) in staff_set)
    research_count = sum(1 for e in occupied_empids if str(e) in research_set)
    guest_count = sum(1 for e in occupied_empids if str(e) in guest_set)
    emp_type_total = staff_count + research_count + guest_count

    # Site palette: teal (brand primary), purple, amber — matching seat type colors
    emp_circ = 314
    def _emp_dash(count):
        return round(count / emp_type_total * emp_circ, 1) if emp_type_total > 0 else 0

    staff_dash = _emp_dash(staff_count)
    research_dash = _emp_dash(research_count)
    guest_dash = _emp_dash(guest_count)

    # Ring uses the same pastel/"-100" tone family as the Seat Type & Room Type
    # donuts (#fee2e2, #dcfce7) so all utilization donuts read as one system;
    # the legend dots keep the saturated accent color for readability.
    return {
        'total': emp_type_total,
        'items': [
            {'name': 'Staff', 'count': staff_count, 'color': '#007367', 'ring_color': '#ccfbf1',
             'dash': staff_dash, 'gap': emp_circ - staff_dash, 'offset': 0},
            {'name': 'Research Faculty', 'count': research_count, 'color': '#5b21b6', 'ring_color': '#ede9fe',
             'dash': research_dash, 'gap': emp_circ - research_dash, 'offset': -staff_dash},
            {'name': 'Guest Faculty', 'count': guest_count, 'color': '#92400e', 'ring_color': '#fef3c7',
             'dash': guest_dash, 'gap': emp_circ - guest_dash, 'offset': -(staff_dash + research_dash)},
        ]
    }


@login_required
@group_required('ADMIN', 'RADMIN')
def space_utilization(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    seat_qs = Seat.objects.filter(is_active=True,room_id__is_active=1).select_related(
        'seat_type', 'seat_status', 'room', 'room__building', 'room__campus', 'room__floor', 'room__block'
    )
    room_qs = Room.objects.filter(is_active=True).select_related(
        'building', 'campus', 'block', 'floor', 'room_type'
    )
    building_qs = Building.objects.filter(is_active=True).select_related('campus')
    if not is_admin:
        seat_ids = get_access_seats(user_id)
        room_ids = get_access_rooms(user_id)
        bldg_ids = get_access_building(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)
        room_qs = room_qs.filter(id__in=room_ids)
        building_qs = building_qs.filter(id__in=bldg_ids)

    total_seats = seat_qs.count()
    occupied_seats = seat_qs.filter(seat_status_id=2).count()
    available_seats = seat_qs.filter(seat_status_id=1).count()
    reserved_seats = seat_qs.filter(seat_status_id=3).count()
    maintenance_seats = seat_qs.filter(seat_status_id=4).count()
    occupancy_rate = round(occupied_seats / total_seats * 100, 1) if total_seats > 0 else 0

    # Seat type breakdown (Cubicles, Cabins, etc.)
    COLORS = ['#007367', '#2B7158', '#1d4ed8', '#5b21b6', '#92400e', '#166534', '#991b1b', '#475569']
    seat_type_stats = compute_seat_type_stats(seat_qs)

    # Employee type breakdown for occupied seats (Staff / Research Faculty / Guest Faculty)
    emp_type_stats = compute_emp_type_stats(seat_qs)

    # Room type breakdown — seats grouped by the room type they sit in (Office, Classroom, Laboratory, etc.)
    room_type_stats = compute_room_type_stats(seat_qs)

    # Building breakdown
    building_stats = []
    max_seats = 1
    for bldg in building_qs.order_by('name'):
        bs = seat_qs.filter(room__building=bldg)
        b_total = bs.count()
        b_occ = bs.filter(seat_status_id=2).count()
        b_avail = bs.filter(seat_status_id=1).count()
        b_res = bs.filter(seat_status_id=3).count()
        b_maint = bs.filter(seat_status_id=4).count()
        b_pct = round(b_occ / b_total * 100) if b_total > 0 else 0

        if b_total > max_seats:
            max_seats = b_total
        building_stats.append({
            'name': bldg.name,
            'code': bldg.code,
            'campus': bldg.campus.name,
            'total': b_total,
            'occupied': b_occ,
            'available': b_avail,
            'reserved': b_res,
            'maintenance': b_maint,
            'pct': b_pct,
        })

    for b in building_stats:
        b['bar_pct'] = round(b['total'] / max_seats * 100) if max_seats > 0 else 0

    # Seat grid by type — individual seats for heatmap
    seat_grid_by_type = []
    for idx, st in enumerate(SeatType.objects.filter(is_active=True)):
        type_seats = seat_qs.filter(seat_type=st,room_id__is_active=1).select_related(
            'seat_status', 'room', 'room__building', 'room__room_type'
        ).order_by('room__building__name', 'room__room_number', 'seat_number')
        seats_data = []
        for s in type_seats:
            seats_data.append({
                'id': s.id,
                'number': s.seat_number,
                'status_id': s.seat_status_id,
                'status_name': s.seat_status.name if s.seat_status else '',
                'seat_type': st.name,
                'room': s.room.room_number if s.room else '',
                'room_name': (s.room.room_name or '') if s.room else '',
                'room_type': s.room.room_type.name if s.room and s.room.room_type else '',
                'building': s.room.building.name if s.room and s.room.building else '',
                'floor': s.room.floor.floor_label if s.room and s.room.floor else '',
                'emp_id': s.current_empid or '',
            })
        t_total = len(seats_data)
        t_occ = sum(1 for s in seats_data if s['status_id'] == 2)
        t_avail = sum(1 for s in seats_data if s['status_id'] == 1)
        seat_grid_by_type.append({
            'name': st.name,
            'icon': st.icon or 'bx bx-chair',
            'color': COLORS[idx % len(COLORS)],
            'total': t_total,
            'occupied': t_occ,
            'available': t_avail,
            'pct': round(t_occ / t_total * 100) if t_total else 0,
            'seats': seats_data,
        })

    # Room stats for detail table
    room_stats = []
    for room in room_qs.order_by('building__name', 'room_number'):
        rs = seat_qs.filter(room=room)
        r_total = rs.count()
        r_occ = rs.filter(seat_status_id=2).count()
        r_avail = rs.filter(seat_status_id=1).count()
        r_pct = round(r_occ / r_total * 100) if r_total > 0 else 0
        room_stats.append({
            'number': room.room_number,
            'room_name': room.room_name or '',
            'building': room.building.name if room.building else '',
            'building_code': room.building.code if room.building else '',
            'floor': room.floor.floor_label if room.floor else '',
            'total': r_total,
            'occupied': r_occ,
            'available': r_avail,
            'pct': r_pct,
        })

    # Ring chart
    circ = 314
    def pct_ring(val):
        return round(val / total_seats * circ, 1) if total_seats > 0 else 0

    avail_ring = pct_ring(available_seats)
    occ_ring = pct_ring(occupied_seats)
    res_ring = pct_ring(reserved_seats)
    seat_allocation_history=seat_allocation_history_departament_wise(campus="BLR")
    max_total = max([d['total'] for d in seat_allocation_history], default=1)
    department_stats = []
    for dept in seat_allocation_history:
        department_stats.append({
            'name': dept['dept_code'],
            'total': dept['total'],
            'pct': round((dept['total'] / max_total) * 100),
        })
    #print(department_stats)
    context = {
        'total_seats': total_seats,
        'occupied_seats': occupied_seats,
        'available_seats': available_seats,
        'reserved_seats': reserved_seats,
        'maintenance_seats': maintenance_seats,
        'occupancy_rate': occupancy_rate,
        'seat_type_stats': seat_type_stats,
        'emp_type_stats': emp_type_stats,
        'room_type_stats': room_type_stats,
        'building_stats': building_stats,
        'seat_grid_by_type': seat_grid_by_type,
        'room_stats': room_stats,
        'seat_statuses': SeatStatus.objects.filter(is_active=True),
        'buildings': building_qs.order_by('name'),
        'floors': Floor.objects.filter(is_active=True, building__in=building_qs).select_related('building').order_by('building__name', 'floor_number'),
        'rooms_list': room_qs.order_by('building__name', 'room_number'),
        'room_types': RoomType.objects.filter(id__in=room_qs.values_list('room_type_id', flat=True)).order_by('name'),
        'available_pct': avail_ring,
        'remaining_pct': circ - avail_ring,
        'occupied_pct': occ_ring,
        'occ_remaining': circ - occ_ring,
        'reserved_pct': res_ring,
        'department_stats': department_stats,
        'res_remaining': circ - res_ring,
        'occupied_offset': -avail_ring,
        'reserved_offset': -(avail_ring + occ_ring),
    }
    return render(request, 'workspace/space_utilization.html', context)


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def filter_room_type_utilization(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    building_id = request.POST.get('building', '').strip()
    room_id = request.POST.get('room', '').strip()

    seat_qs = Seat.objects.filter(is_active=True, room_id__is_active=1)

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    if building_id:
        seat_qs = seat_qs.filter(room__building_id=building_id)
    if room_id:
        seat_qs = seat_qs.filter(room_id=room_id)

    room_type_stats = compute_room_type_stats(seat_qs)

    return JsonResponse({'status': 1, 'items': room_type_stats})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def occupied_seats_by_type(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    seat_type_name = request.POST.get('seat_type', '').strip()

    seat_qs = Seat.objects.filter(
        is_active=True, room_id__is_active=1, seat_status_id=2
    ).select_related('seat_type', 'room', 'room__building', 'room__floor', 'room__campus')

    if seat_type_name:
        seat_qs = seat_qs.filter(seat_type__name=seat_type_name)

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    data = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        emp = resolve_employee_details(s.current_empid)
        data.append({
            'seat_number' : s.seat_number,
            'seat_type'   : s.seat_type.name if s.seat_type else '',
            'room'        : s.room.room_number if s.room else '',
            'room_name'   : (s.room.room_name or '') if s.room else '',
            'floor'       : s.room.floor.floor_label if s.room and s.room.floor else '',
            'building'    : s.room.building.name if s.room and s.room.building else '',
            'campus'      : s.room.campus.name if s.room and s.room.campus else '',
            'empid'       : s.current_empid or '',
            'emp_name'    : emp['name'] or '',
            'designation' : emp['designation'] or '',
            'department'  : emp['department'] or '',
        })

    return JsonResponse({'status': 1, 'seat_type': seat_type_name, 'count': len(data), 'data': data})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def available_seats_by_type(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    seat_type_name = request.POST.get('seat_type', '').strip()

    seat_qs = Seat.objects.filter(
        is_active=True, room_id__is_active=1, seat_status_id=1
    ).select_related('seat_type', 'room', 'room__building', 'room__floor', 'room__campus')

    if seat_type_name:
        seat_qs = seat_qs.filter(seat_type__name=seat_type_name)

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    data = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        data.append({
            'seat_number' : s.seat_number,
            'seat_type'   : s.seat_type.name if s.seat_type else '',
            'room'        : s.room.room_number if s.room else '',
            'room_name'   : (s.room.room_name or '') if s.room else '',
            'floor'       : s.room.floor.floor_label if s.room and s.room.floor else '',
            'building'    : s.room.building.name if s.room and s.room.building else '',
            'campus'      : s.room.campus.name if s.room and s.room.campus else '',
            'empid'       : '',
            'emp_name'    : '',
            'designation' : '',
            'department'  : '',
        })

    return JsonResponse({'status': 1, 'seat_type': seat_type_name, 'count': len(data), 'data': data})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def occupied_seats_by_emp_type(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    emp_type = request.POST.get('emp_type', '').strip()

    seat_qs = Seat.objects.filter(
        is_active=True, room_id__is_active=1, seat_status_id=2
    ).exclude(current_empid__isnull=True).exclude(current_empid='').select_related(
        'seat_type', 'room', 'room__building', 'room__floor', 'room__campus'
    )

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    data = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        emp = resolve_employee_details(s.current_empid)
        if emp_type and emp['source'] != emp_type:
            continue
        data.append({
            'seat_number' : s.seat_number,
            'seat_type'   : s.seat_type.name if s.seat_type else '',
            'room'        : s.room.room_number if s.room else '',
            'room_name'   : (s.room.room_name or '') if s.room else '',
            'floor'       : s.room.floor.floor_label if s.room and s.room.floor else '',
            'building'    : s.room.building.name if s.room and s.room.building else '',
            'campus'      : s.room.campus.name if s.room and s.room.campus else '',
            'empid'       : s.current_empid or '',
            'emp_name'    : emp['name'] or '',
            'designation' : emp['designation'] or '',
            'department'  : emp['department'] or '',
        })

    return JsonResponse({'status': 1, 'emp_type': emp_type, 'count': len(data), 'data': data})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def occupied_seats_by_room_type(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    room_type_name = request.POST.get('room_type', '').strip()
    building_id = request.POST.get('building', '').strip()
    room_id = request.POST.get('room', '').strip()

    seat_qs = Seat.objects.filter(
        is_active=True, room_id__is_active=1, seat_status_id=2
    ).select_related('seat_type', 'room', 'room__building', 'room__floor', 'room__campus', 'room__room_type')

    if room_type_name:
        seat_qs = seat_qs.filter(room__room_type__name=room_type_name)
    if building_id:
        seat_qs = seat_qs.filter(room__building_id=building_id)
    if room_id:
        seat_qs = seat_qs.filter(room_id=room_id)

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    data = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        emp = resolve_employee_details(s.current_empid)
        data.append({
            'seat_number' : s.seat_number,
            'seat_type'   : s.seat_type.name if s.seat_type else '',
            'room'        : s.room.room_number if s.room else '',
            'room_name'   : (s.room.room_name or '') if s.room else '',
            'floor'       : s.room.floor.floor_label if s.room and s.room.floor else '',
            'building'    : s.room.building.name if s.room and s.room.building else '',
            'campus'      : s.room.campus.name if s.room and s.room.campus else '',
            'empid'       : s.current_empid or '',
            'emp_name'    : emp['name'] or '',
            'designation' : emp['designation'] or '',
            'department'  : emp['department'] or '',
        })

    return JsonResponse({'status': 1, 'room_type': room_type_name, 'count': len(data), 'data': data})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def available_seats_by_room_type(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    room_type_name = request.POST.get('room_type', '').strip()
    building_id = request.POST.get('building', '').strip()
    room_id = request.POST.get('room', '').strip()

    seat_qs = Seat.objects.filter(
        is_active=True, room_id__is_active=1, seat_status_id=1
    ).select_related('seat_type', 'room', 'room__building', 'room__floor', 'room__campus', 'room__room_type')

    if room_type_name:
        seat_qs = seat_qs.filter(room__room_type__name=room_type_name)
    if building_id:
        seat_qs = seat_qs.filter(room__building_id=building_id)
    if room_id:
        seat_qs = seat_qs.filter(room_id=room_id)

    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    data = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        data.append({
            'seat_number' : s.seat_number,
            'seat_type'   : s.seat_type.name if s.seat_type else '',
            'room'        : s.room.room_number if s.room else '',
            'room_name'   : (s.room.room_name or '') if s.room else '',
            'floor'       : s.room.floor.floor_label if s.room and s.room.floor else '',
            'building'    : s.room.building.name if s.room and s.room.building else '',
            'campus'      : s.room.campus.name if s.room and s.room.campus else '',
            'empid'       : '',
            'emp_name'    : '',
            'designation' : '',
            'department'  : '',
        })

    return JsonResponse({'status': 1, 'room_type': room_type_name, 'count': len(data), 'data': data})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def filter_seat_grid(request):
    user_id = request.user.id
    is_admin = UserGroups.objects.filter(user_id=user_id, group__name='ADMIN', is_active=1).exists()

    seat_type_name = request.POST.get('seat_type', '').strip()
    status_id = request.POST.get('status', '').strip()
    building_id = request.POST.get('building', '').strip()
    floor_id = request.POST.get('floor', '').strip()
    room_id = request.POST.get('room', '').strip()
    room_type_id = request.POST.get('room_type', '').strip()

    seat_qs = Seat.objects.filter(is_active=True,room_id__is_active=1).select_related(
        'seat_type', 'seat_status', 'room', 'room__building', 'room__floor', 'room__room_type'
    )
    if not is_admin:
        seat_ids = get_access_seats(user_id)
        seat_qs = seat_qs.filter(id__in=seat_ids)

    if seat_type_name:
        seat_qs = seat_qs.filter(seat_type__name=seat_type_name)
    if status_id:
        seat_qs = seat_qs.filter(seat_status_id=status_id)
    if building_id:
        seat_qs = seat_qs.filter(room__building_id=building_id)
    if floor_id:
        seat_qs = seat_qs.filter(room__floor_id=floor_id)
    if room_id:
        seat_qs = seat_qs.filter(room_id=room_id)
    if room_type_id:
        seat_qs = seat_qs.filter(room__room_type_id=room_type_id)

    seats = []
    for s in seat_qs.order_by('room__building__name', 'room__room_number', 'seat_number'):
        seats.append({
            'id': s.id,
            'number': s.seat_number,
            'status_id': s.seat_status_id,
            'status_name': s.seat_status.name if s.seat_status else '',
            'room': s.room.room_number if s.room else '',
            'room_name': (s.room.room_name or '') if s.room else '',
            'room_type': s.room.room_type.name if s.room and s.room.room_type else '',
            'building': s.room.building.name if s.room and s.room.building else '',
            'floor': s.room.floor.floor_label if s.room and s.room.floor else '',
            'emp_id': s.current_empid or '',
            'type_name': s.seat_type.name if s.seat_type else '',
            'type_icon': s.seat_type.icon if s.seat_type and s.seat_type.icon else 'bx bx-chair',
        })

    html = render_to_string('workspace/_seat_grid_cells.html', {'seats': seats})
    return JsonResponse({'status': 200, 'count': len(seats), 'html': html})


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def search_employee(request):
    user_id = request.user.id
    is_radmin = UserGroups.objects.filter(user_id=user_id, group__name='RADMIN', is_active=1).exists()

    emp_id     = request.GET.get('emp_id', '').strip()
    result     = None
    emp_info   = None
    no_access  = False
    not_allocated = False

    if emp_id:
        # Try to fetch employee master info from GITAM DB
        try:
            emp_obj = EmployeeMaster.objects.using('GITAM').filter(empid=emp_id).values(
                'emp_name', 'campus', 'college_code', 'dept_code', 'designation', 'emailid'
            ).first()
            if emp_obj:
                emp_obj['source'] = 'Employee Master'

            if not emp_obj:
                emp_obj = ResearchFaculty.objects.filter(emp_id=emp_id, is_active=True).values(
                    'name', 'email', 'college_code', 'dept_code', 'designation'
                ).first()
                if emp_obj:
                    emp_obj['emp_name'] = emp_obj.pop('name')
                    emp_obj['emailid']  = emp_obj.pop('email')
                    emp_obj['campus']   = None
                    emp_obj['source']   = 'Research Faculty'

            if not emp_obj:
                emp_obj = GlearnGuestStaffMaster.objects.using('GITAM').filter(empid=emp_id).values(
                    'emp_name', 'campus', 'college_code', 'dept_code'
                ).first()
                if emp_obj:
                    emp_obj['designation'] = 'Guest Faculty'
                    emp_obj['emailid'] = ''
                    emp_obj['source'] = 'Guest Staff'
            emp_info = emp_obj
        except Exception:
            emp_info = None

        seat_qs = Seat.objects.filter(
            current_empid=emp_id, is_active=True, seat_status_id=2
        ).select_related(
            'seat_type', 'seat_status',
            'room', 'room__building', 'room__building__campus',
            'room__floor', 'room__block',
        )

        if is_radmin:
            access_campuses = list(get_access_campus(user_id))
            campus_map = {1: 'VSP', 2: 'HYD', 3: 'BLR'}
            campus_codes = [campus_map[c] for c in access_campuses if c in campus_map]
            if campus_codes:
                seat_qs = seat_qs.filter(room__campus__name__in=campus_codes)
            else:
                seat_qs = seat_qs.none()
            if Seat.objects.filter(current_empid=emp_id, is_active=True, seat_status_id=2).exists() and not seat_qs.exists():
                no_access = True

        seat = seat_qs.first()
        if seat:
            room = seat.room
            # get allocated_on from last active history record
            hist = SeatAllocationHistory.objects.filter(
                empid=emp_id, seat=seat, is_active=True
            ).order_by('-allocated_date').first()
            result = {
                'seat_number' : seat.seat_number,
                'seat_type'   : seat.seat_type.name if seat.seat_type else '—',
                'room'        : room.room_number if room else '—',
                'floor'       : room.floor.floor_label if room and room.floor else '—',
                'block'       : room.block.name if room and room.block else '—',
                'building'    : room.building.name if room and room.building else '—',
                'campus'      : room.campus.name if room and room.campus else '—',
                'allocated_on': hist.allocated_date.strftime('%d %b %Y') if hist and hist.allocated_date else '—',
            }
        elif not no_access:
            not_allocated = True

    # Allocation history
    history = []
    if emp_id:
        hist_qs = SeatAllocationHistory.objects.filter(empid=emp_id).select_related(
            'seat', 'seat__seat_type', 'seat__room',
            'seat__room__building', 'seat__room__floor', 'seat__room__block',
            'seat_status', 'createdby'
        ).order_by('-allocated_date')
        if is_radmin:
            access_campuses = list(get_access_campus(user_id))
            campus_map = {1: 'VSP', 2: 'HYD', 3: 'BLR'}
            campus_codes = [campus_map[c] for c in access_campuses if c in campus_map]
            if campus_codes:
                hist_qs = hist_qs.filter(campus__in=campus_codes)
            else:
                hist_qs = hist_qs.none()
        for h in hist_qs:
            s = h.seat
            r = s.room if s else None
            history.append({
                'seat'        : s.seat_number if s else '—',
                'seat_type'   : s.seat_type.name if s and s.seat_type else '—',
                'room'        : r.room_number if r else '—',
                'floor'       : r.floor.floor_label if r and r.floor else '—',
                'block'       : r.block.name if r and r.block else '—',
                'building'    : r.building.name if r and r.building else '—',
                'campus'      : r.campus.name if r and r.campus else '—',
                'status'      : h.seat_status.name if h.seat_status else '—',
                'status_id'   : h.seat_status_id,
                'allocated_on': h.allocated_date.strftime('%d %b %Y') if h.allocated_date else '—',
                'released_on' : h.released_date.strftime('%d %b %Y') if h.released_date else '—',
                'is_active'   : h.is_active,
                'by'          : h.createdby.get_full_name() if h.createdby else '—',
            })

    context = {
        'emp_id': emp_id,
        'emp_info': emp_info,
        'result': result,
        'not_allocated': not_allocated,
        'no_access': no_access,
        'is_radmin': is_radmin,
        'history': history,
    }
    return render(request, 'workspace/search_employee.html', context)


def seat_allocation_history_departament_wise(campus):
    return (
        SeatAllocationHistory.objects
        .filter(campus=campus)
        .values('dept_code')
        .annotate(total=Count('id'))
        .order_by('-total')
    )
@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def department_wise_details(request):

    campus = request.POST.get("campus")
    department = request.POST.get("department")
    qs = SeatAllocationHistory.objects.filter(
        campus=campus,
        dept_code=department,
        is_active=True
    ).select_related(
        'seat',
        'seat__seat_type',
        'seat__room',
        'createdby'
    )

    emp_ids = list({obj.empid for obj in qs if obj.empid})
    emp_info = {}
    if emp_ids:
        for row in EmployeeMaster.objects.using('GITAM').filter(empid__in=emp_ids).values(
            'empid', 'emp_name', 'college_code'
        ):
            emp_info[str(row['empid'])] = {
                'name'  : row.get('emp_name') or '',
                'school': row.get('college_code') or '',
            }
        missing = [e for e in emp_ids if str(e) not in emp_info]
        if missing:
            for row in GlearnGuestStaffMaster.objects.using('GITAM').filter(empid__in=missing).values(
                'empid', 'emp_name', 'college_code'
            ):
                emp_info[str(row['empid'])] = {
                    'name'  : row.get('emp_name') or '',
                    'school': row.get('college_code') or '',
                }

    data = []
    for i, obj in enumerate(qs, start=1):
        ei = emp_info.get(str(obj.empid), {})
        data.append({
            "sno"           : i,
            "empid"         : obj.empid,
            "emp_name"      : ei.get('name', ''),
            "campus"        : obj.campus,
            "school"        : ei.get('school', ''),
            "department"    : obj.dept_code,
            "designation"   : obj.designation,
            "seat_id"       : obj.seat.id if obj.seat else "",
            "seat_type"     : obj.seat.seat_type.name if obj.seat and obj.seat.seat_type else "",
            "seat_number"   : obj.seat.seat_number if obj.seat else "",
            "room"          : obj.seat.room.room_number if obj.seat and obj.seat.room else "",
            "allocated_date": obj.allocated_date.strftime("%d-%m-%Y"),
            "created_by"    : obj.createdby.first_name if obj.createdby else "",
        })

    return JsonResponse({"data": data})

@login_required
@group_required('ADMIN', 'RADMIN')
def get_room_details(request):
    room = Room.objects.select_related(
        "campus",
        "building",
        "block",
        "floor",
        "room_type"
    ).get(id=request.POST.get("room_id"))
    return JsonResponse({
        "status":1,
        "data":{
            "id":room.id,
            "campus_id":room.campus_id,
            "building_id":room.building_id,
            "block_id":room.block_id,
            "floor_id":room.floor_id,
            "room_number":room.room_number,
            "room_name":room.room_name or "",
            "room_type_id":room.room_type_id
        }
    })
def resolve_employee_name(empid):
    """3-tier lookup used wherever an assigned seat's occupant needs a display name:
    EmployeeMaster -> ResearchFaculty -> GlearnGuestStaffMaster."""
    if not empid:
        return None

    emp_row = EmployeeMaster.objects.using('GITAM').filter(empid=empid).values('emp_name').last()
    if emp_row and emp_row.get('emp_name'):
        return emp_row.get('emp_name')

    rf_row = ResearchFaculty.objects.filter(emp_id=empid, is_active=True).values('name').last()
    if rf_row and rf_row.get('name'):
        return rf_row.get('name')

    gl_row = GlearnGuestStaffMaster.objects.using('GITAM').filter(empid=empid).values('emp_name').last()
    if gl_row and gl_row.get('emp_name'):
        return gl_row.get('emp_name')

    return None


def resolve_employee_details(empid):
    """Same 3-tier lookup as resolve_employee_name(), but also returns designation,
    department, and source (Staff / Research Faculty / Guest Faculty)."""
    if not empid:
        return {'name': None, 'designation': None, 'department': None, 'source': None}

    emp_row = EmployeeMaster.objects.using('GITAM').filter(empid=empid).values('emp_name', 'job_description', 'dept_name').last()
    if emp_row and emp_row.get('emp_name'):
        return {'name': emp_row.get('emp_name'), 'designation': emp_row.get('job_description'),
                'department': emp_row.get('dept_name'), 'source': 'Staff'}

    rf_row = ResearchFaculty.objects.filter(emp_id=empid, is_active=True).values('name', 'designation', 'department').last()
    if rf_row and rf_row.get('name'):
        return {'name': rf_row.get('name'), 'designation': rf_row.get('designation'),
                'department': rf_row.get('department'), 'source': 'Research Faculty'}

    gl_row = GlearnGuestStaffMaster.objects.using('GITAM').filter(empid=empid).values('emp_name', 'dept_code').last()
    if gl_row and gl_row.get('emp_name'):
        return {'name': gl_row.get('emp_name'), 'designation': 'Guest Faculty',
                'department': gl_row.get('dept_code'), 'source': 'Guest Faculty'}

    return {'name': None, 'designation': None, 'department': None, 'source': None}


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def delete_room(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid request."
        })

    room_id = request.POST.get("room_id")

    try:
        room = Room.objects.get(id=room_id)

        occupied_seats = Seat.objects.filter(
            room_id=room_id, is_active=True, seat_status_id=2
        )
        if occupied_seats.exists():
            assigned_users = []
            for seat in occupied_seats:
                emp_name = resolve_employee_name(seat.current_empid)
                assigned_users.append({
                    "seat_number": seat.seat_number,
                    "empid": seat.current_empid or "",
                    "emp_name": (emp_name or "").strip() or "—",
                })

            return JsonResponse({
                "status": 300,
                "message": f"This room has {len(assigned_users)} user(s) currently assigned. "
                           f"Please assign them to another room before deleting this room.",
                "assigned_users": assigned_users
            })

        room_number = room.room_number
        room.delete()
        return JsonResponse({
            "status": 1,
            "message": f"Room '{room_number}' deleted permanently."
        })
    except Room.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Room not found."
        })


@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def delete_seat(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid request."
        })

    seat_id = request.POST.get("seat_id")

    try:
        seat = Seat.objects.select_related('room').get(id=seat_id)

        if seat.seat_status_id == 2 and seat.current_empid:
            emp_name = resolve_employee_name(seat.current_empid)
            assigned_users = [{
                "empid": seat.current_empid,
                "emp_name": (emp_name or "").strip() or "—",
                "room_number": seat.room.room_number if seat.room else "—",
            }]

            return JsonResponse({
                "status": 300,
                "message": f"Seat '{seat.seat_number}' is already assigned to a user. "
                           f"Please assign them to another seat/room before deleting this seat.",
                "assigned_users": assigned_users
            })

        seat_number = seat.seat_number
        seat.delete()
        return JsonResponse({
            "status": 1,
            "message": f"Seat '{seat_number}' deleted permanently."
        })
    except Seat.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Seat not found."
        })
@login_required
@group_required('ADMIN', 'RADMIN')
@csrf_exempt
def toggle_room_status(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid request."
        })

    room_id = request.POST.get("room_id")

    try:
        room = Room.objects.get(id=room_id)
        if room.is_active and room.Seat_room.filter(is_active=True, seat_status_id=2).exists():
            return JsonResponse({
                "status": 300,
                "is_active": room.is_active,
                "message": "This room is already allocated. Please remove the allocation before deactivating."
            })

        room.is_active = not room.is_active
        room.save()
        return JsonResponse({
            "status": 1,
            "is_active": room.is_active,
            "message": "Room activated successfully." if room.is_active else "Room deactivated successfully."
        })
    except Room.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Room not found."
        })
@login_required
@group_required('ADMIN', 'RADMIN')
def get_block_details(request):

    if request.method == "POST":

        block = Block.objects.select_related(
            "campus",
            "building",
            "block_type"
        ).get(id=request.POST.get("block_id"))

        return JsonResponse({
            "status":1,
            "data":{
                "id":block.id,
                "name":block.name,
                "code":block.code,
                "campus_id":block.campus_id,
                "building_id":block.building_id,
                "block_type_id":block.block_type_id
            }
        })

    return JsonResponse({
        "status":0,
        "message":"Invalid Request"
    })
@login_required
@group_required('ADMIN', 'RADMIN')
def delete_block(request):

    if request.method != "POST":
        return JsonResponse({
            "status": 0,
            "message": "Invalid request."
        })

    block_id = request.POST.get("block_id")

    try:
        block = Block.objects.get(id=block_id)
        block.is_active = False      # Soft delete
        block.save()

        return JsonResponse({
            "status": 1,
            "message": "Block deleted successfully."
        })

    except Block.DoesNotExist:
        return JsonResponse({
            "status": 0,
            "message": "Block not found."
        })

@login_required
@group_required('ADMIN', 'RADMIN')
def get_seat_details(request):
    if request.method == "POST":
        seat_id = request.POST.get("seat_id")

        try:
            seat = Seat.objects.select_related(
                "room",
                "room__building",
                "room__floor",
                "room__building__campus",
                "seat_type",
                "seat_status"
            ).get(id=seat_id)

            return JsonResponse({
                "status": 1,
                "seat": {
                    "id": seat.id,
                    "seat_number": seat.seat_number,
                    "current_empid": seat.current_empid or "",

                    "campus_id": seat.room.building.campus_id,
                    "campus_name": seat.room.building.campus.name,

                    "building_name": seat.room.building.name,

                    "block_name": seat.room.block.name,

                    "floor_name": seat.room.floor.floor_label,
                    "room_id": seat.room_id,
                    "room_name": seat.room.room_number,

                    "seat_type_id": seat.seat_type_id,
                    "seat_type_name": seat.seat_type.name,

                    "seat_status_id": seat.seat_status_id,
                    "seat_status_name": seat.seat_status.name,
                }
            })

        except Seat.DoesNotExist:
            return JsonResponse({
                "status": 0,
                "message": "Seat not found."
            })

    return JsonResponse({
        "status": 0,
        "message": "Invalid request."
    })


def check_seat_exists(request):

    if request.method == "POST":

        seat_number = request.POST.get("seat_number", "").strip()
        seat_id = request.POST.get("seat_id")
        room_id = request.POST.get("room_id")

        query = Seat.objects.filter(
            room_id=room_id,
            seat_number__iexact=seat_number,
            is_active=True
        )
        # Exclude the current seat while editing
        if seat_id:
            query = query.exclude(id=seat_id)

        if query.exists():

            return JsonResponse({
                "exists": True,
                "message": f"Seat number '{seat_number}' already exists in this room."
            })

        return JsonResponse({
            "exists": False,
            "message": "Seat number is available."
        })

    return JsonResponse({
        "exists": False,
        "message": "Invalid request."
    })


@login_required
@group_required('ADMIN', 'RADMIN')
def update_seat(request):
    if request.method == "POST":
        seat_id = request.POST.get("seat_id")
        seat_number = request.POST.get("edit_seat_num", "").strip()
        room_id = request.POST.get("room_id")
        seat_type_id = request.POST.get("seat_type", "").strip()
        try:

            if Seat.objects.filter(
                room_id=room_id,
                seat_number__iexact=seat_number,
                is_active=True
            ).exclude(id=seat_id).exists():
                return JsonResponse({
                    "exists": True,
                    "message": f"Seat number '{seat_number}' already exists in this room."
                })
            else:
                seat = Seat.objects.get(id=seat_id, room_id=room_id)
                if seat.seat_number != seat_number:
                    SeatHistory.objects.create(
                        seat_id=seat_id,
                        previous_seat_number=seat.seat_number,
                        current_seat_number=seat_number,
                        createdby_id=request.user.id)
                seat.seat_number = seat_number
                if seat_type_id:
                    seat.seat_type_id = seat_type_id
                seat.updatedby = request.user
                seat.save()
                return JsonResponse({
                    "status": 200,
                    "message": "Seat updated successfully."
                })

        except Seat.DoesNotExist:
            return JsonResponse({
                "status": 0,
                "message": "Seat not found."
            })

    return JsonResponse({
        "status": 0,
        "message": "Invalid request."
    })