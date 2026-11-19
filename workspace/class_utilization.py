import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.db.models.functions import Trim, Upper
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from usermanagement.models import User, UserGroups, ResearchFaculty
from .models import ClassroomBooking, RoomMaster, TimeTableMaster


DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_DAYS = DAYS[:5]
GITAM_DATABASE = "GITAM"
SEMESTER_PATTERN = re.compile(r"^(\d{4})-(\d{4})#(ODD|EVEN)$")
DAY_LABELS = {day.upper(): day for day in DAYS}
TIME_START_DEFAULT = 8
TIME_END_DEFAULT = 16   # 4 PM – default view cap
TIME_END_AFTER_HOURS = 22  # extended cap when user opts in


def _normalise(value):
    return str(value or "").strip().upper()


def _normalise_semester(value):
    semester = _normalise(value)
    return semester if SEMESTER_PATTERN.fullmatch(semester) else ""


def _semester_sort_key(value):
    match = SEMESTER_PATTERN.fullmatch(value)
    return int(match.group(1)), 0 if match.group(3) == "ODD" else 1


def _semester_choices(values):
    return sorted(
        {semester for semester in (_normalise_semester(value) for value in values) if semester},
        key=_semester_sort_key,
    )


def get_current_semester(today=None):
    """
    Computes the current semester flag based on calendar date.
    July - December (month >= 7): Academic year YYYY-(YYYY+1)#ODD
    January - June (month < 7): Academic year (YYYY-1)-YYYY#EVEN
    """
    today = today or (timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date())
    start_year = today.year if today.month >= 7 else today.year - 1
    term = "ODD" if today.month >= 7 else "EVEN"
    return f"{start_year}-{start_year + 1}#{term}"


def _get_active_semester(semesters, today=None):
    if not semesters:
        return ""
    current = get_current_semester(today)
    return current if current in semesters else semesters[-1]


def _load_teacher_email_map():
    email_map = {}
    try:
        users = User.objects.filter(is_active=True).exclude(email='').values('username', 'emp_id', 'email')
        for u in users:
            if u.get('username'):
                email_map[_normalise(u['username'])] = u['email'].strip()
            if u.get('emp_id'):
                email_map[_normalise(u['emp_id'])] = u['email'].strip()
        rfs = ResearchFaculty.objects.filter(is_active=True).exclude(email='').values('emp_id', 'email')
        for rf in rfs:
            if rf.get('emp_id'):
                email_map[_normalise(rf['emp_id'])] = rf['email'].strip()
    except Exception:
        pass
    return email_map


def _building_key_value(campus, building):
    return "|".join((_normalise(campus), _normalise(building)))


def _building_label(building_code, building_name):
    code = str(building_code or "").strip()
    name = str(building_name or "").strip()
    if code and name and _normalise(code) != _normalise(name):
        return f"{code} ({name})"
    return code or name or "Unknown building"


def _day_headers(days, today=None):
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    headers = []
    for day in days:
        day_date = monday + timedelta(days=DAYS.index(day))
        headers.append({
            "day": day,
            "date": day_date.strftime("%b ") + str(day_date.day),
            "iso_date": day_date.isoformat(),
        })
    return headers


def _room_key_value(campus, building, room_code):
    return "|".join((_normalise(campus), _normalise(building), _normalise(room_code)))


def _room_type_label(record):
    labels = []
    for value in (record.get("room_category"), record.get("theory_lab"), record.get("room_type")):
        label = str(value or "").strip()
        if label and _normalise(label) not in {_normalise(item) for item in labels}:
            labels.append(label)
    return " / ".join(labels) or "Room"


def _room_quality(room):
    return (
        bool(room["building_code"])
        + (room["room_type_label"] != "Room")
        + (room["room_name"] != room["room_code"])
        + (room["capacity"] is not None)
    )


def _build_room_catalog(records):
    room_by_key = {}
    aliases = defaultdict(set)
    for record in records:
        campus = str(record.get("campus_code") or "").strip()
        building_code = str(record.get("building_code") or "").strip()
        building_name = str(record.get("building_name") or "").strip()
        room_code = str(record.get("room_code") or "").strip()
        room_number = str(record.get("room_number") or "").strip()
        display_code = room_code or room_number
        building_key = building_code or building_name
        if not campus or not display_code:
            continue

        key = _room_key_value(campus, building_key, display_code)
        room = {
            "key": key,
            "campus": campus,
            "campus_key": _normalise(campus),
            "building": building_name or building_code or "Unknown building",
            "building_code": building_code,
            "building_key": _building_key_value(campus, building_key),
            "room_code": display_code,
            "room_name": str(record.get("room_name") or "").strip() or display_code,
            "room_type_label": _room_type_label(record),
            "capacity": record.get("capacity"),
            "floor_code": str(record.get("floor_code") or "").strip(),
            "maintenance": any(str(record.get(field) or "").strip().upper() in {"M", "MAINTENANCE"} for field in ("room_status", "current_status")),
        }

        existing = room_by_key.get(key)
        if existing is None:
            room_by_key[key] = room
        elif _room_quality(room) > _room_quality(existing):
            room_by_key[key] = room
        else:
            for field in ("building", "building_code", "room_name", "room_type_label", "capacity"):
                if (
                    not existing[field]
                    or field == "room_name" and existing[field] == existing["room_code"]
                    or field == "room_type_label" and existing[field] == "Room"
                    or field == "building" and existing[field] == "Unknown building"
                ) and room[field]:
                    existing[field] = room[field]

        for alias in (room_code, room_number, display_code):
            if alias:
                aliases[(_normalise(campus), _normalise(alias))].add(key)

    rooms = sorted(
        room_by_key.values(),
        key=lambda room: (room["campus"], room["building"], room["room_name"], room["room_code"]),
    )
    return rooms, room_by_key, aliases


def _resolve_room(row, room_by_key, aliases):
    campus = _normalise(row.get("campus_code"))
    room_number = _normalise(row.get("room_number"))
    candidate_keys = set(aliases.get((campus, room_number), ()))
    building = _normalise(row.get("building_name"))
    if building:
        matching_keys = {
            key for key in candidate_keys
            if building in {
                _normalise(room_by_key[key]["building_code"]),
                _normalise(room_by_key[key]["building"]),
            }
        }
        if matching_keys:
            candidate_keys = matching_keys
    if len(candidate_keys) != 1:
        return None
    return room_by_key[next(iter(candidate_keys))]


def _minutes(value):
    return value.hour * 60 + value.minute


def _scheduled_hours_by_day(schedules, selected_days):
    hours_by_day = {day: 0.0 for day in selected_days}
    for row in schedules:
        if row["room_master_match"] and row["weekday"] in hours_by_day:
            hours_by_day[row["weekday"]] += row["duration_minutes"] / 60
    return hours_by_day


def _load_semester_choices():
    values = TimeTableMaster.objects.using(GITAM_DATABASE).exclude(
        sem_flag__isnull=True
    ).values_list("sem_flag", flat=True).distinct()
    return _semester_choices(values)


def _load_room_catalog():
    records = RoomMaster.objects.using(GITAM_DATABASE).filter(
        is_active=True
    ).exclude(
        room_status__iexact="D"
    ).exclude(
        current_status__iexact="D"
    ).values(
        "room_code", "room_name", "building_code", "building_name", "campus_code",
        "capacity", "room_status", "current_status", "room_type", "room_category",
        "theory_lab", "room_number", "floor_code",
    )
    return _build_room_catalog(records)


def _load_timetable(semester, room_by_key, aliases, teacher_email_map=None, *, room_key=None):
    rows = TimeTableMaster.objects.using(GITAM_DATABASE).annotate(
        semester_key=Upper(Trim("sem_flag")),
        status_key=Upper(Trim("status_flag")),
    ).filter(
        semester_key=semester,
    ).filter(
        Q(status_key="A") | Q(status_key=semester)
    )
    if room_key is not None:
        campus = room_by_key[room_key]['campus_key']
        room_numbers = [number for (alias_campus, number), keys in aliases.items() if alias_campus == campus and room_key in keys]
        rows = rows.alias(campus_key=Upper(Trim('campus_code')), room_alias=Upper(Trim('room_number'))).filter(
            campus_key=campus, room_alias__in=room_numbers,
        )
    rows = rows.values(
        "id", "subject_code", "subject_name", "weekday", "from_time", "to_time",
        "section", "semester", "batch", "branch_code", "course_code", "degree_code",
        "dept_code", "college_code", "campus_code", "empid", "empname", "room_number",
        "building_name",
    ).iterator(chunk_size=2000)

    teacher_email_map = teacher_email_map or {}
    schedules = []
    seen = set()
    for row in rows:
        day = DAY_LABELS.get(_normalise(row["weekday"]))
        start, end = row["from_time"], row["to_time"]
        if not day or not isinstance(start, time) or not isinstance(end, time):
            continue
        start_minutes, end_minutes = _minutes(start), _minutes(end)
        if start_minutes >= end_minutes:
            continue

        room = _resolve_room(row, room_by_key, aliases)
        campus = room["campus"] if room else str(row["campus_code"] or "").strip()
        building = room["building"] if room else str(row["building_name"] or "").strip()
        room_code = room["room_code"] if room else str(row["room_number"] or "").strip()
        room_name = room["room_name"] if room else room_code
        building_key = room["building_key"] if room else _building_key_value(campus, building)

        empid_str = str(row["empid"] or "").strip()
        empname_str = str(row["empname"] or "").strip()
        t_email = ""
        if empid_str:
            t_email = teacher_email_map.get(_normalise(empid_str), "")
            if not t_email:
                t_email = f"{empid_str}@gitam.edu"

        schedule = {
            "id": row["id"],
            "campus": campus,
            "campus_key": _normalise(campus),
            "building": building or "Unknown building",
            "building_key": building_key,
            "room_code": room_code or "Unknown room",
            "room_name": room_name or "Unknown room",
            "room_type_label": room["room_type_label"] if room else "",
            "room_key": room["key"] if room else "",
            "room_master_match": room is not None,
            "subject_code": str(row["subject_code"] or "").strip() or "N/A",
            "subject_name": str(row["subject_name"] or "").strip() or "Untitled subject",
            "course_code": str(row["course_code"] or "").strip(),
            "section": str(row["section"] or "").strip(),
            "semester": row["semester"],
            "batch": str(row["batch"] or "").strip(),
            "branch_code": str(row["branch_code"] or "").strip(),
            "degree_code": str(row["degree_code"] or "").strip(),
            "dept_code": str(row["dept_code"] or "").strip(),
            "college_code": str(row["college_code"] or "").strip(),
            "instructor_name": empname_str or "Not provided",
            "instructor_id": empid_str or "Not provided",
            "instructor_email": t_email or "Not provided",
            "weekday": day,
            "start_minutes": start_minutes,
            "end_minutes": end_minutes,
            "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M"),
            "duration_minutes": end_minutes - start_minutes,
        }
        signature = tuple(
            _normalise(schedule[field]) if isinstance(schedule[field], str) else schedule[field]
            for field in (
                "campus", "building", "room_code", "subject_code", "subject_name",
                "course_code", "section", "semester", "batch", "branch_code",
                "degree_code", "dept_code", "college_code", "instructor_id",
                "instructor_name", "weekday", "start_minutes", "end_minutes",
            )
        )
        if signature in seen:
            continue
        seen.add(signature)
        schedules.append(schedule)

    schedules.sort(key=lambda row: (
        DAYS.index(row["weekday"]), row["start_minutes"], row["campus"],
        row["building"], row["room_name"], row["subject_code"],
    ))
    return schedules


def _filters(request, rooms, schedules, semesters, reference_date=None):
    campus_labels = {room["campus_key"]: room["campus"] for room in rooms}
    for row in schedules:
        if row.get("campus_key"):
            campus_labels.setdefault(row["campus_key"], row.get("campus", row["campus_key"]))
    campus_options = [
        {"key": key, "label": campus_labels[key]}
        for key in sorted(campus_labels)
    ]

    selected_campus = _normalise(request.GET.get("campus"))
    if selected_campus not in campus_labels:
        selected_campus = ""

    available_rooms = [
        room for room in rooms
        if not selected_campus or room["campus_key"] == selected_campus
    ]
    building_options_by_key = {}
    for room in rooms:
        building_options_by_key.setdefault(room["building_key"], {
            "key": room["building_key"],
            "label": _building_label(room["building_code"], room["building"]),
            "campus_key": room["campus_key"],
        })
    for row in schedules:
        if (
            row["building_key"]
            and row["building_key"] not in building_options_by_key
        ):
            building_label = row.get("building") or row.get("building_key") or "Unknown building"
            building_options_by_key[row["building_key"]] = {
                "key": row["building_key"],
                "label": building_label,
                "campus_key": row.get("campus_key", ""),
            }
    all_buildings = sorted(
        building_options_by_key.values(),
        key=lambda building: (building["label"], building["campus_key"]),
    )
    building_options = [building for building in all_buildings
                        if not selected_campus or building["campus_key"] == selected_campus]

    selected_building = str(request.GET.get("building") or "").strip()
    if not any(building["key"] == selected_building for building in building_options):
        selected_building = ""
    if selected_building:
        available_rooms = [
            room for room in available_rooms
            if room["building_key"] == selected_building
        ]

    floor_rooms = list(available_rooms)
    floor_choices = sorted({room.get('floor_code','') or '__unrecorded__' for room in floor_rooms}) if selected_campus and selected_building else []
    selected_floor = str(request.GET.get('floor') or '')
    requested_room = next((room for room in floor_rooms if room['key']==request.GET.get('room')),None)
    if requested_room and not selected_floor:
        selected_floor = requested_room.get('floor_code','') or '__unrecorded__'
    if selected_floor not in floor_choices:
        selected_floor = ''
    if selected_floor:
        available_rooms = [room for room in available_rooms if (room.get('floor_code','') or '__unrecorded__')==selected_floor]

    room_key = str(request.GET.get("room") or "").strip()
    room_keys = {room["key"] for room in available_rooms}
    selected_room_key = room_key if room_key in room_keys else ""
    if selected_room_key:
        available_rooms = [room for room in available_rooms if room["key"] == selected_room_key]

    # Note: Day filter removed per user request so the full week is shown.
    scoped_schedules = [
        row for row in schedules
        if (not selected_campus or row["campus_key"] == selected_campus)
        and (not selected_building or row["building_key"] == selected_building)
        and (not selected_room_key or row["room_key"] == selected_room_key)
    ]

    search = str(request.GET.get("q") or "").strip()
    if search:
        needle = search.casefold()
        visible_schedules = [
            row for row in scoped_schedules
            if any(needle in str(row[field] or "").casefold() for field in (
                "subject_code", "subject_name", "course_code", "section", "batch",
                "branch_code", "degree_code", "dept_code", "college_code",
                "instructor_name", "instructor_id", "instructor_email",
                "room_code", "room_name", "building", "campus",
            ))
        ]
        schedule_room_keys = {
            row["room_key"] for row in visible_schedules if row["room_key"]
        }
        room_text_matches = {
            room["key"] for room in available_rooms
            if any(needle in str(room[field] or "").casefold() for field in (
                "room_code", "room_name", "building", "campus", "room_type_label",
            ))
        }
        room_matches = schedule_room_keys | room_text_matches
        room_choices = [room for room in available_rooms if room["key"] in room_matches]
    else:
        visible_schedules = scoped_schedules
        room_matches = {room["key"] for room in available_rooms}
        room_choices = available_rooms

    # Follow the viewed date automatically; stale URL semester values cannot pin a term.
    current_semester = get_current_semester(reference_date)
    selected_semester = current_semester if current_semester in semesters else ''

    return {
        "campuses": campus_options,
        "selected_campus": selected_campus,
        "buildings": building_options,
        "all_buildings": all_buildings,
        "selected_building": selected_building,
        "room_choices": room_choices,
        "selected_room_key": selected_room_key,
        "selected_floor":selected_floor, "floor_choices":[{"key":value,"label":value if value != "__unrecorded__" else "Floor not recorded"} for value in floor_choices],
        "search": search,
        "semester_choices": semesters,
        "selected_semester": selected_semester,
        "current_semester": current_semester,
        "classes": visible_schedules,
        "occupancy_classes": scoped_schedules,
        "room_matches": room_matches,
    }


def _csv_response(schedules, semester):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="class-utilization-timetable.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow((
        "Semester", "Campus", "Building", "Room", "Room code", "Room type",
        "Day", "Start", "End", "Duration minutes", "Subject code", "Subject",
        "Course", "Section", "Batch", "Branch", "Degree", "Department",
        "College", "Instructor", "Instructor ID", "Instructor Email", "Matched room master",
    ))
    for row in schedules:
        writer.writerow((
            semester, row["campus"], row["building"], row["room_name"], row["room_code"],
            row["room_type_label"], row["weekday"], row["start_time"], row["end_time"],
            row["duration_minutes"], row["subject_code"], row["subject_name"],
            row["course_code"], row["section"], row["batch"], row["branch_code"],
            row["degree_code"], row["dept_code"], row["college_code"],
            row["instructor_name"], row["instructor_id"], row.get("instructor_email", ""),
            "Yes" if row["room_master_match"] else "No",
        ))
    return response


# Reuse the timetable catalog above; booking endpoints live in the workflow module.
from .booking_workflow import book_classroom, review_classroom_booking, classroom_requests


@login_required
@require_GET
def class_utilization(request):
    from .booking_workflow import role
    active_role = role(request.user)
    revision_context = None
    if request.GET.get('revision'):
        from .booking_revisions import load_draft, RevisionError, return_url
        token = request.GET['revision']
        try:
            draft, revision_booking = load_draft(request, token)
        except RevisionError as error:
            return error.response()
        query = request.GET.copy()
        for name, field in [('campus','campus'),('building','building'),('room','room_key'),('date','booking_date')]:
            if name not in query and draft['fields'].get(field):
                query[name] = str(draft['fields'][field])
        query.setdefault('include_after_hours','0')
        query.pop('booking_id',None)
        request.GET = query
        revision_context = {'token':token,'booking_id':revision_booking.pk,
                            'fields':draft['fields'],'selection':draft.get('selection'),
                            'return_url':return_url(token),'revision':draft['revision']}
    data_errors = []
    try:
        semesters = _load_semester_choices()
    except (DatabaseError, KeyError, TypeError, ValueError):
        semesters = []
        data_errors.append("The timetable master could not be loaded from the GITAM database.")

    try:
        rooms, room_by_key, room_aliases = _load_room_catalog()
    except (DatabaseError, KeyError, TypeError, ValueError):
        rooms, room_by_key, room_aliases = [], {}, {}
        data_errors.append("The room master could not be loaded from the GITAM database.")

    if active_role == 'HOI':
        rooms = [room for room in rooms if _normalise(room['campus']) == _normalise(request.user.campus)]
        room_by_key = {room['key']:room for room in rooms}
        room_aliases = {alias: keys & set(room_by_key) for alias,keys in room_aliases.items()}

    from .booking_workflow import visible
    selected_booking = None
    selected_date = None
    if request.GET.get('booking_id'):
        booking_id = request.GET['booking_id']
        if not booking_id.isdigit():
            raise Http404('Booking not found.')
        selected_booking = get_object_or_404(visible(request.user), pk=int(booking_id))
        room = room_by_key.get(selected_booking.room_key)
        if room is None:
            room = _resolve_room({'campus_code':selected_booking.campus_code, 'building_name':selected_booking.building_name, 'room_number':selected_booking.room_code},room_by_key,room_aliases)
        if room is None:
            raise Http404('The booked classroom is not present in the active room master.')
        params = request.GET.copy()
        for name, value in {'campus':room['campus_key'], 'building':room['building_key'], 'room':room['key'], 'date':selected_booking.booking_date.isoformat()}.items():
            params[name] = value
        params.pop('q',None)
        params['semester'] = get_current_semester(selected_booking.booking_date)
        request.GET = params
    if request.GET.get('date'):
        try:
            selected_date = date.fromisoformat(request.GET['date'])
        except ValueError:
            return HttpResponseBadRequest('Choose a valid timetable date (YYYY-MM-DD).')

    now = timezone.now()
    if timezone.is_aware(now):
        now = timezone.localtime(now)
    today = now.date()
    current_minutes = _minutes(now.time())
    reference_day = selected_date or today
    week_start = reference_day - timedelta(days=reference_day.weekday())
    week_end = week_start + timedelta(days=6)
    from .holidays import closures_on, day_annotations, year_available
    teacher_emails = _load_teacher_email_map()

    # Resolve trusted deep links (booking/revision) from the actual room catalog.
    linked_room = room_by_key.get(request.GET.get('room',''))
    if linked_room:
        query = request.GET.copy()
        query.setdefault('campus',linked_room['campus'])
        query.setdefault('building',linked_room['building_key'])
        query.setdefault('floor',linked_room.get('floor_code','') or '__unrecorded__')
        request.GET = query

    filters = _filters(request, rooms, [], semesters, reference_date=selected_date)
    revision_popup = revision_context is not None and request.GET.get('revision_popup') == '1'
    maintenance_picker = request.GET.get('maintenance_picker') == '1'
    if maintenance_picker and active_role != 'ADMIN':
        return HttpResponseForbidden('Only Admin can schedule classroom maintenance.')
    timetable_popup = not revision_popup and (maintenance_picker or request.GET.get('timetable_popup') == '1' and bool(filters['selected_room_key']))
    scoped_room = filters['selected_room_key'] if timetable_popup or revision_popup else ''
    timetable_scope = {'room_key': scoped_room} if scoped_room else {}
    schedules = []
    if filters["selected_semester"]:
        try:
            schedules = _load_timetable(
                filters["selected_semester"], room_by_key, room_aliases, teacher_emails, **timetable_scope
            )
        except (DatabaseError, KeyError, TypeError, ValueError):
            data_errors.append("The selected timetable term could not be loaded.")

    if active_role == 'HOI':
        schedules = [row for row in schedules if _normalise(row['campus']) == _normalise(request.user.campus)]

    card_schedules = schedules
    if not scoped_room and filters['selected_semester'] != get_current_semester(today):
        try:
            card_schedules = _load_timetable(get_current_semester(today),room_by_key,room_aliases,teacher_emails)
        except (DatabaseError, KeyError, TypeError, ValueError):
            card_schedules = []
            data_errors.append('Current room availability could not be fully checked.')
    schedules = [row for row in schedules if not closures_on(
        week_start + timedelta(days=DAYS.index(row['weekday'])), row.get('campus', ''))]
    filters = _filters(request, rooms, schedules, semesters, reference_date=selected_date)
    selected_semester = filters["selected_semester"]
    master_buildings = {room['building_key'] for room in rooms}
    filters['buildings'] = [building for building in filters['buildings'] if building['key'] in master_buildings]
    if not selected_semester:
        data_errors.append('Timetable data for '+filters['current_semester']+' is unavailable. No other semester has been substituted.')
    if request.GET.get("export") == "csv":
        return _csv_response(filters["classes"], selected_semester)

    search = filters["search"].casefold()
    candidate_room_keys = filters["room_matches"]
    if not search:
        candidate_room_keys = {room["key"] for room in filters["room_choices"]}

    range_start, range_end = week_start, week_end
    room_by_key = {room["key"]: room for room in rooms}

    from .booking_workflow import role, visible
    booking_role = role(request.user)
    is_reviewer = role(request.user) in ('ADMIN', 'HOD')
    pending_requests_count = 0

    booking_events = []
    blocking_events = []
    if selected_semester:
        try:
            bookings = visible(request.user).filter(
                booking_date__range=(range_start, range_end),
                is_active=True,
            ).exclude(status='withdrawn')

            for booking in bookings:
                matching_rooms = [
                    room for room in rooms
                    if room["key"] == booking.room_key or (room["campus_key"] == _normalise(booking.campus_code)
                    and _normalise(room["room_code"]) == _normalise(booking.room_code)
                    and _normalise(booking.building_name) in {
                        _normalise(room["building"]),
                        _normalise(room["building_code"]),
                    })
                ]
                if len(matching_rooms) != 1:
                    continue
                room = matching_rooms[0]
                if room["key"] not in candidate_room_keys:
                    continue
                booked_by = booking.booked_by
                t_name = booking.teacher_name or (booked_by.get_full_name() if booked_by else "") or (booked_by.get_username() if booked_by else "") or "Not provided"
                t_id = booking.teacher_id or (booked_by.get_username() if booked_by else "") or "Not provided"
                t_email = booking.teacher_email or (booked_by.email if booked_by else "") or (f"{t_id}@gitam.edu" if t_id != "Not provided" else "Not provided")
                sub_code = booking.subject_code or "N/A"
                sub_name = booking.subject_name or booking.title or "N/A"

                booking_events.append({
                    "id": booking.id,
                    "room_key": room["key"],
                    "weekday": DAYS[booking.booking_date.weekday()],
                    "booking_date": booking.booking_date.isoformat(),
                    "start_minutes": _minutes(booking.from_time),
                    "end_minutes": _minutes(booking.to_time),
                    "start_time": booking.from_time.strftime("%H:%M"),
                    "end_time": booking.to_time.strftime("%H:%M"),
                    "duration_hours": booking.duration_hours,
                    "title": booking.title,
                    "purpose": booking.purpose,
                    "details": booking.details,
                    "teacher_name": t_name,
                    "teacher_id": t_id,
                    "teacher_email": t_email,
                    "subject_code": sub_code,
                    "subject_name": sub_name,
                    "status": booking.status,
                    "status_label": booking.get_status_display(),
                    "campus": booking.campus_code,
                    "building": booking.building_name,
                    "review_comment": booking.review_comment,
                    "reviewed_by": booking.reviewed_by.get_full_name() or booking.reviewed_by.username if booking.reviewed_by else '',
                    "reviewed_at": booking.reviewed_at.strftime('%d %b %Y %H:%M') if booking.reviewed_at else '',
                    "admin_comment": booking.admin_comment,
                    "can_review": False,
                    "room_name": room["room_name"],
                    "room_code": room["room_code"],
                })
        except DatabaseError:
            data_errors.append("Classroom bookings could not be loaded from the application database.")

    try:
        for held in ClassroomBooking.objects.filter(booking_date__range=(range_start, range_end), is_active=True, status__in=['pending','hod_approved','confirmed']):
            room = room_by_key.get(held.room_key) or _resolve_room({'campus_code':held.campus_code,'building_name':held.building_name,'room_number':held.room_code},room_by_key,room_aliases)
            if room and room['key'] in candidate_room_keys:
                blocking_events.append({'room_key':room['key'],'weekday':DAYS[held.booking_date.weekday()],'start_minutes':_minutes(held.from_time),'end_minutes':_minutes(held.to_time),'status':held.status})
    except DatabaseError:
        data_errors.append('Reservation availability could not be loaded.')

    room_by_key = {room["key"]: room for room in rooms}
    candidate_rooms = len(candidate_room_keys)
    booking_room_catalog = [
        room_by_key[key] for key in sorted(candidate_room_keys) if key in room_by_key
    ]
    room_indexes = {
        room["key"]: index for index, room in enumerate(booking_room_catalog)
    }

    # Weekends toggle: default Monday to Friday; if requested, include Saturday and Sunday
    include_weekends = request.GET.get("include_weekends") in ("1", "true", "on", "yes")
    visible_days = DAYS if include_weekends else DEFAULT_DAYS
    selected_days = visible_days

    # After-hours toggle: default 8 AM – 4 PM; if requested, extend to 10 PM
    include_after_hours = request.GET.get("include_after_hours") in ("1", "true", "on", "yes")
    effective_time_end = TIME_END_AFTER_HOURS if include_after_hours else TIME_END_DEFAULT

    hours_by_day = _scheduled_hours_by_day(filters["classes"], selected_days)
    for booking in blocking_events:
        if booking["status"] == "confirmed" and booking["weekday"] in hours_by_day:
            hours_by_day[booking["weekday"]] += (
                booking["end_minutes"] - booking["start_minutes"]
            ) / 60
    scheduled_hours = sum(hours_by_day.values())
    busiest_day = max(hours_by_day, key=hours_by_day.get) if any(hours_by_day.values()) else "—"

    timed_schedules = schedules
    if timed_schedules:
        grid_start = min(
            TIME_START_DEFAULT,
            min(row["start_minutes"] // 60 for row in timed_schedules),
        )
        # Cap grid_end to effective_time_end unless a class runs past it
        actual_end = max((row["end_minutes"] + 59) // 60 for row in timed_schedules)
        grid_end = max(effective_time_end, min(actual_end, effective_time_end))
        # If include_after_hours, also include any class that goes beyond 4 PM
        if include_after_hours:
            grid_end = max(grid_end, actual_end)
    else:
        grid_start, grid_end = TIME_START_DEFAULT, effective_time_end
    if not include_after_hours:
        grid_start, grid_end = TIME_START_DEFAULT, TIME_END_DEFAULT
    grid_end = max(grid_end, grid_start + 1)

    occupancy = defaultdict(list)
    for row in filters["occupancy_classes"]:
        if row["room_key"]:
            occupancy[(row["room_key"], row["weekday"])].append(row)

    available_room_keys = set()
    from .classroom_maintenance import available_reasons, window_map
    maintenance_rooms = {room['key'] for room in rooms
                         if not filters['selected_campus'] or room['campus_key'] == filters['selected_campus']}
    maintenance_windows = window_map(week_start, week_end, maintenance_rooms)
    for room_key in candidate_room_keys:
        if room_by_key[room_key].get('maintenance'):
            continue
        for day in selected_days:
            if closures_on(week_start + timedelta(days=DAYS.index(day)), room_by_key[room_key]['campus']):
                continue
            day_events = occupancy.get((room_key, day), [])
            if any(not any(
                _minutes(window.start) < (hour + 1) * 60 and _minutes(window.end) > hour * 60
                for window in maintenance_windows.get((room_key, week_start + timedelta(days=DAYS.index(day))), ())
            ) and not any(
                event["start_minutes"] < (hour + 1) * 60
                and event["end_minutes"] > hour * 60
                for event in day_events
            ) and not any(
                booking["room_key"] == room_key
                and booking["weekday"] == day
                and booking["start_minutes"] < (hour + 1) * 60
                and booking["end_minutes"] > hour * 60
                for booking in blocking_events
            ) for hour in range(grid_start, grid_end)):
                available_room_keys.add(room_key)
                break

    classify_room_cards = bool(filters['selected_floor'] and not filters['selected_room_key'])
    rooms_with_open_slots = set()
    rooms_with_booked_slots = set()
    maintenance_selection_days = set()
    grid_rows = []
    for hour in range(grid_start, grid_end):
        grid_row = {
            "label": f"{hour:02d}:00 - {hour + 1:02d}:00",
            "start_time": f"{hour:02d}:00",
            "end_time": f"{hour + 1:02d}:00",
            "cells": [],
        }
        for day in visible_days:
            booking_date = week_start + timedelta(days=DAYS.index(day))
            # Collect all matching events for this hour/day slot
            raw_events = [
                event for event in filters["classes"]
                if event["weekday"] == day
                and event["start_minutes"] < (hour + 1) * 60
                and event["end_minutes"] > hour * 60
            ]
            # Deduplicate: same subject_code + instructor in same slot = same class
            seen_events = set()
            events = []
            for event in raw_events:
                dedup_key = (
                    event.get("subject_code", ""),
                    event.get("instructor_id", ""),
                    event.get("room_code", ""),
                    event.get("start_minutes"),
                    event.get("end_minutes"),
                )
                if dedup_key not in seen_events:
                    seen_events.add(dedup_key)
                    events.append(event)
            cell_bookings = [
                booking for booking in booking_events
                if booking["weekday"] == day
                and booking["start_minutes"] < (hour + 1) * 60
                and booking["end_minutes"] > hour * 60
            ]
            busy_room_keys = {
                room_key for room_key in candidate_room_keys
                if any(
                    event["start_minutes"] < (hour + 1) * 60
                    and event["end_minutes"] > hour * 60
                    for event in occupancy.get((room_key, day), [])
                )
            }
            classify_slot = classify_room_cards and (
                booking_date > today or booking_date == today and (hour + 1) * 60 > current_minutes
            )
            if classify_slot:
                booked_keys = busy_room_keys | {
                    booking['room_key'] for booking in blocking_events
                    if booking['status'] in ('hod_approved', 'confirmed') and booking['weekday'] == day
                    and booking['start_minutes'] < (hour + 1) * 60 and booking['end_minutes'] > hour * 60
                }
                rooms_with_booked_slots.update(
                    key for key in booked_keys if not closures_on(booking_date, room_by_key[key]['campus'])
                )
            busy_room_keys.update(booking['room_key'] for booking in cell_bookings if booking['status'] in ('pending','hod_approved','confirmed'))
            busy_room_keys.update(booking['room_key'] for booking in blocking_events if booking['weekday'] == day and booking['start_minutes'] < (hour+1)*60 and booking['end_minutes'] > hour*60)
            maintenance_keys = {
                key for key in candidate_room_keys
                if any(_minutes(window.start) < (hour + 1) * 60 and _minutes(window.end) > hour * 60
                       for window in maintenance_windows.get((key, booking_date), ()))
            }
            busy_room_keys.update(maintenance_keys)
            free_rooms = [
                room_by_key[key] for key in sorted(candidate_room_keys - busy_room_keys)
                if key in room_by_key and not room_by_key[key].get('maintenance')
                and not closures_on(booking_date, room_by_key[key]['campus'])
            ]
            if classify_slot and (booking_date > today or hour * 60 >= current_minutes):
                rooms_with_open_slots.update(room['key'] for room in free_rooms)
            elapsed_minutes = 24 * 60 if booking_date < today else current_minutes if booking_date == today else -1
            day_info = day_annotations(booking_date, [room_by_key[key]['campus'] for key in candidate_room_keys if key in room_by_key])
            maintenance_available = (
                booking_role == 'ADMIN' and bool(filters['selected_room_key']) and not maintenance_picker
                and not day_info['is_holiday'] and (booking_date > today or booking_date == today and hour*60 >= current_minutes)
                and any(room['key'] == filters['selected_room_key'] for room in free_rooms)
            )
            if maintenance_available:
                maintenance_selection_days.add(booking_date.isoformat())
            display_bookings = [
                dict(booking, elapsed=booking['status'] in ('hod_approved','confirmed')
                     and booking['end_minutes'] <= elapsed_minutes)
                for booking in cell_bookings
            ]
            grid_row["cells"].append({
                "day": day,
                **day_info,
                "highlighted": bool(selected_booking and day == DAYS[selected_booking.booking_date.weekday()] and _minutes(selected_booking.from_time) < (hour+1)*60 and _minutes(selected_booking.to_time) > hour*60),
                "events": [dict(event, elapsed=event['end_minutes'] <= elapsed_minutes) for event in events],
                "bookings": display_bookings,
                "free_rooms": free_rooms,
                "has_held_requests": any(held["weekday"] == day and held["start_minutes"] < (hour+1)*60 and held["end_minutes"] > hour*60 for held in blocking_events),
                "has_pending_holds": any(held['status'] == 'pending' and held['weekday'] == day and held['start_minutes'] < (hour+1)*60 and held['end_minutes'] > hour*60 for held in blocking_events),
                "has_approved_bookings": any(held['status'] in ('hod_approved', 'confirmed') and held['weekday'] == day and held['start_minutes'] < (hour+1)*60 and held['end_minutes'] > hour*60 for held in blocking_events),
                "has_maintenance": bool(maintenance_keys),
                "elapsed": (hour+1)*60 <= elapsed_minutes,
                "maintenance_available": maintenance_available,
                "free_room_indexes_json": json.dumps([
                    room_indexes[room["key"]] for room in free_rooms
                ]),
                "booking_date": booking_date.isoformat(),
            })
        grid_rows.append(grid_row)

    # One message per holiday column; prefer an empty cell so existing cards stay readable.
    for day in visible_days:
        holiday_cells = [cell for row in grid_rows for cell in row['cells'] if cell['day'] == day and cell['is_holiday']]
        empty_cells = [cell for cell in holiday_cells if not cell['events'] and not cell['bookings']]
        if empty_cells:
            empty_cells[len(empty_cells)//2]['holiday_message'] = True

    params = request.GET.copy()
    params.pop("export", None)
    params["semester"] = selected_semester
    params["export"] = "csv"
    if include_weekends:
        params["include_weekends"] = "1"
    if include_after_hours:
        params["include_after_hours"] = "1"

    booking_room_catalog_data = [
        {
            "key": room["key"],
            "campus": room["campus"],
            "building": room["building"],
            "room_name": room["room_name"],
            "room_code": room["room_code"],
            "building_key": room["building_key"],
            "capacity": room["capacity"],
            "floor_code":room.get("floor_code",""),
        }
        for room in booking_room_catalog
    ]

    from .utilization_summary import summarize_utilization
    summary = None if timetable_popup or revision_popup else summarize_utilization(
        booking_room_catalog,
        [*filters['occupancy_classes'], *[event for event in blocking_events if event['status'] == 'confirmed']],
        selected_days, grid_start, grid_end,
        closures={(room['key'], day) for room in booking_room_catalog for day in selected_days
                  if closures_on(week_start + timedelta(days=DAYS.index(day)), room['campus'])},
    )
    headers = _day_headers(visible_days, today=reference_day)
    campuses_in_view = [room_by_key[key]['campus'] for key in candidate_room_keys if key in room_by_key]
    for header in headers:
        header.update(day_annotations(date.fromisoformat(header['iso_date']), campuses_in_view))
    def week_url(day):
        query = request.GET.copy()
        query.pop('booking_id', None)
        query.pop('export', None)
        query['date'] = day.isoformat()
        query['semester'] = selected_semester
        return '?' + query.urlencode()
    from .classroom_selection import selection_context
    if timetable_popup:
        back_query = request.GET.copy()
        for key in ('timetable_popup', 'room', 'booking_id'):
            back_query.pop(key, None)
        selection = {'back_to_classrooms_url': '?' + back_query.urlencode()}
    else:
        selection = selection_context(request, rooms, card_schedules, filters, today,
                                      partially_booked=rooms_with_open_slots & rooms_with_booked_slots,
                                      maintenance_windows=maintenance_windows,grid_hours=(grid_start,grid_end))
    context = {
        **selection,
        "revision_context": revision_context,
        "week_start": week_start, "week_work_end": week_start + timedelta(days=4),
        "previous_week_url": week_url(week_start - timedelta(days=7)),
        "next_week_url": week_url(week_start + timedelta(days=7)),
        "current_week_url": week_url(today),
        "holiday_calendar_available": all(year_available(year) for year in {week_start.year, week_end.year}),
        "design_summary": summary,
        **filters,
        "grid_rows": grid_rows,
        "visible_days": visible_days,
        "day_headers": headers,
        "maintenance_selection_days": maintenance_selection_days,
        "selected_date": reference_day.isoformat(),
        "selected_booking": selected_booking,
        "time_range_label": f"{grid_start:02d}:00-{grid_end:02d}:00",
        "scheduled_hours": round(scheduled_hours, 1),
        "available_rooms": len(available_room_keys),
        "room_count": candidate_rooms,
        "utilization": round(
            scheduled_hours / (candidate_rooms * len(selected_days) * (grid_end - grid_start)) * 100
        ) if candidate_rooms else 0,
        "busiest_day": busiest_day,
        "unmatched_count": sum(not row["room_master_match"] for row in filters["classes"]),
        "show_schedule": bool(filters["selected_room_key"]) or maintenance_picker,
        "maintenance_picker": maintenance_picker,
        "maintenance_room": room_by_key.get(filters['selected_room_key']),
        "maintenance_building_label": next((room['building'] for room in rooms
                                            if room['building_key']==filters['selected_building']), ''),
        "maintenance_reasons": available_reasons() if active_role == 'ADMIN' and not maintenance_picker else [],
        "today_iso": today.isoformat(),
        "booking_room_catalog_json": booking_room_catalog_data,
        "booking_events": booking_events,
        "include_weekends": include_weekends,
        "include_after_hours": include_after_hours,
        "booking_role": booking_role,
        "can_book": booking_role in ("TEACHER", "ADMIN") and not maintenance_picker,
        "is_reviewer": is_reviewer,
        "pending_requests_count": pending_requests_count,
        "export_url": f"?{params.urlencode()}",
        "data_error": " ".join(data_errors),
    }
    context['timetable_popup'] = timetable_popup
    context['revision_popup'] = revision_popup
    context['timetable_layout'] = 'workspace/timetable_popup.html' if timetable_popup or revision_popup else 'base.html'
    response = render(request, "workspace/class_utilization.html", context)
    if timetable_popup or revision_popup:
        response['X-Frame-Options'] = 'SAMEORIGIN'
    return response
