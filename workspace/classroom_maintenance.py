"""Maintenance schedules backed by the classroom catalog and booking mutex."""
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from functools import wraps
from hashlib import sha256
from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.signing import BadSignature, SignatureExpired, dumps, loads
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import F, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .booking_workflow import lock_bookings, role
from .models import ClassroomBooking, ClassroomMaintenance, ClassroomMaintenanceReason, ClassroomMaintenanceRoom, ClassroomMaintenanceWindow


DEFAULT_REASONS = (
    'Electrical Issue', 'Benches / Furniture Not Available', 'Projector Not Working',
    'Air Conditioning Not Working', 'Cleaning / Housekeeping', 'Civil Maintenance',
    'Network / Internet Issue', 'Plumbing Issue', 'Other',
)
SALT = 'classroom-maintenance-review'
FLOOR_UNDO_SALT = 'classroom-maintenance-floor-undo'


def scope_fields(scope, rooms):
    target = rooms[0]
    floors = {room.get('floor_code') or '__unrecorded__' for room in rooms}
    targets = sorted(floors) if scope == 'floor' else (
        sorted(room['key'] for room in rooms) if scope == 'room' else [])
    return {
        'scope': scope, 'campus': target['campus'], 'building_key': target['building_key'],
        'building_name': target['building'],
        'floor': next(iter(floors)) if scope != 'building' and len(floors) == 1 else '',
        'room_key': target['key'] if scope == 'room' and len(rooms) == 1 else '',
        'room_codes': [room['room_code'] for room in rooms], 'scope_targets': targets,
    }


def floor_undo_token(user, campus, building, floor, records, room_keys):
    return dumps({'user': user.pk, 'campus': campus, 'building': building, 'floor': floor,
                  'records': records, 'rooms': sorted(room_keys)}, salt=FLOOR_UNDO_SALT, compress=True)


def admin_only(view):
    @login_required
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if role(request.user) != 'ADMIN':
            return HttpResponseForbidden('Only Admin can manage classroom maintenance.')
        return view(request, *args, **kwargs)
    return guarded


def active_windows(start, end):
    return ClassroomMaintenanceWindow.objects.filter(
        maintenance__state='open', date__range=(start, end),
    )


def maintenance_blocks(room_key, day, start, end):
    return active_windows(day, day).filter(
        maintenance__rooms__room_key=room_key, start__lt=end, end__gt=start,
    ).exists()


def window_map(start, end, room_keys):
    """Read display windows in one query, using trusted room keys."""
    result = defaultdict(list)
    if not room_keys:
        return result
    queryset = active_windows(start, end).filter(
        maintenance__rooms__room_key__in=room_keys,
    ).select_related('maintenance')
    for window in queryset.annotate(room_key=F('maintenance__rooms__room_key')):
        result[window.room_key, window.date].append(window)
    return result


def available_reasons():
    return [*DEFAULT_REASONS, *ClassroomMaintenanceReason.objects.order_by('name').values_list('name', flat=True)]


def maintenance_status(record, now):
    if record.state != 'open':
        return record.get_state_display()

    def local_naive(value):
        return timezone.localtime(value).replace(tzinfo=None) if timezone.is_aware(value) else value

    now = local_naive(now)
    windows = list(record.windows.all())
    first = min((datetime.combine(slot.date, slot.start) for slot in windows),
                default=datetime.combine(record.start_date, time.min))
    last = max((datetime.combine(slot.date, slot.end) for slot in windows),
               default=datetime.combine(record.end_date, time.max))
    deadline = local_naive(record.expected_completion) if record.expected_completion else last
    if now.date() > record.end_date or now >= deadline:
        return 'Overdue'
    return 'Upcoming' if now < first else 'Ongoing'


def display_window(window):
    record = window.maintenance
    return {'id': record.pk, 'scope': record.get_scope_display(), 'date': window.date,
            'start': window.start.strftime('%H:%M'), 'end': window.end.strftime('%H:%M'),
            'reasons': record.reasons, 'description': record.description,
            'duration': record.get_duration_display(), 'expected_completion': record.expected_completion,
            'recurring': record.recurrence}


def covers_full_day(windows, start_hour, end_hour):
    """A room is fully maintained when at least one date has no open hour."""
    by_date = defaultdict(list)
    for window in windows:
        by_date[window.date].append((window.start.hour*60+window.start.minute,
                                    window.end.hour*60+window.end.minute))
    start, end = start_hour*60, end_hour*60
    for spans in by_date.values():
        cursor = start
        for left,right in sorted(spans):
            if left > cursor:
                break
            cursor = max(cursor,right)
            if cursor >= end:
                return True
    return False


def scope_rooms(data, rooms):
    scope = data.get('scope')
    building = data.get('building')
    floor = data.get('floor', '')
    room_key = data.get('room', '')
    if scope not in ('room', 'floor', 'building'):
        raise ValueError('Select a classroom, floor or building scope.')
    affected = [room for room in rooms if room['building_key'] == building
                and (not data.get('campus') or room['campus_key'] == str(data['campus']).strip().upper())]
    values = data.get('targets') or ([floor] if scope == 'floor' else [room_key] if scope == 'room' else [])
    if not isinstance(values,list) or any(not isinstance(value,str) or not value for value in values):
        raise ValueError('Select valid maintenance targets.')
    if scope == 'floor':
        affected = [room for room in affected if (room.get('floor_code') or '__unrecorded__') in values]
        if set(values) != {room.get('floor_code') or '__unrecorded__' for room in affected}:
            raise ValueError('Every selected floor must belong to the building.')
    if scope == 'room':
        affected = [room for room in affected if room['key'] in values
                    and (not floor or (room.get('floor_code') or '__unrecorded__') == floor)]
        if set(values) != {room['key'] for room in affected}:
            raise ValueError('Every selected classroom must belong to the selected location.')
    if not affected:
        raise ValueError('Select an active classroom or a floor/building with active classrooms.')
    return affected


def local_now():
    now = timezone.now()
    return timezone.localtime(now) if timezone.is_aware(now) else now


def parse_schedule(data, rooms, *, now, editing=False, selected_rooms=None, cap_recurrence=False):
    affected = scope_rooms(data, rooms)
    if selected_rooms is not None:
        keys = {room['key'] for room in selected_rooms}
        affected = [room for room in affected if room['key'] in keys]
        if keys != {room['key'] for room in affected}:
            raise ValueError('Every selected classroom must belong to the selected location.')
    recurring = data.get('recurrence') is True
    reason_names = data.get('reasons', [])
    valid_reasons = available_reasons()
    if not isinstance(reason_names, list) or not reason_names or any(name not in valid_reasons for name in reason_names):
        raise ValueError('Select at least one valid maintenance reason.')
    duration = data.get('duration') or 'short'
    if duration not in dict(ClassroomMaintenance._meta.get_field('duration').choices):
        raise ValueError('Select an expected rectification duration.')
    description = str(data.get('description') or '').strip()
    if len(description) > 5000:
        raise ValueError('Keep the description within 5,000 characters.')
    expected = data.get('expected_completion')
    expected = datetime.fromisoformat(expected) if expected else None
    if expected and settings.USE_TZ and timezone.is_naive(expected):
        expected = timezone.make_aware(expected, timezone.get_current_timezone())
    elif expected and not settings.USE_TZ and timezone.is_aware(expected):
        expected = timezone.make_naive(expected, timezone.get_current_timezone())
    recurrence_limit = None
    if recurring and expected and cap_recurrence:
        recurrence_limit = (timezone.make_naive(expected, timezone.get_current_timezone())
                            if timezone.is_aware(expected) else expected)
    selected = data.get('selections')
    if not isinstance(selected, list) or not selected or len(selected) > (168 if recurring else 366*24):
        raise ValueError('Select at least one maintenance day.')
    rules = defaultdict(list)
    for entry in selected:
        day = date.fromisoformat(entry['date'])
        key = day.weekday() if recurring else day
        start, end = (datetime.strptime(entry[field], '%H:%M').time() for field in ('start', 'end'))
        if start >= end:
            raise ValueError('Every maintenance end time must be after its start time.')
        rules[key].append((start,end))
    for key,spans in rules.items():
        merged = []
        for start,end in sorted(spans):
            if merged and start < merged[-1][1]:
                raise ValueError('Maintenance hours on the same day cannot overlap.')
            if merged and start == merged[-1][1] and not data.get('timetable_selection'):
                merged[-1] = (merged[-1][0],end)
            else:
                merged.append((start,end))
        rules[key] = merged
    if recurring:
        first, last = (date.fromisoformat(data[field]) for field in ('start_date', 'end_date'))
    else:
        first, last = min(rules), max(rules)
    if (not editing and first < now.date()) or last < first or (last-first).days > 365:
        raise ValueError('Use current or future dates spanning at most 366 days.')
    windows = []
    matches_range = False
    for offset in range((last-first).days+1):
        day = first+timedelta(days=offset)
        for start,end in rules.get(day.weekday() if recurring else day, ()):
            matches_range = True
            if recurrence_limit:
                if day > recurrence_limit.date() or day == recurrence_limit.date() and start >= recurrence_limit.time():
                    continue
                if day == recurrence_limit.date():
                    end = min(end, recurrence_limit.time())
            if editing and (day < now.date() or day == now.date() and end <= now.time()):
                continue
            if day == now.date() and end <= now.time():
                raise ValueError('Select a time range that has not already ended.')
            windows.append((day,start,end))
    if not windows:
        if recurring and not matches_range:
            raise ValueError('No selected weekdays occur in this recurrence range.')
        raise ValueError('No selected maintenance time slots remain. Choose a date and time that has not ended.')
    if data.get('starts_at'):
        start_bound = datetime.fromisoformat(data['starts_at'])
        if timezone.is_aware(start_bound):
            start_bound = timezone.make_naive(start_bound, timezone.get_current_timezone())
        end_bound = expected
        if end_bound and timezone.is_aware(end_bound):
            end_bound = timezone.make_naive(end_bound, timezone.get_current_timezone())
        if not end_bound or end_bound <= start_bound:
            raise ValueError('Expected completion must be after the start date and time.')
        if any(datetime.combine(day,start)<start_bound or datetime.combine(day,end)>end_bound for day,start,end in windows):
            raise ValueError('Maintenance hours must fall within the start and completion dates and times.')
    if expected and expected.date() < first:
        raise ValueError('Expected completion must be on or after the first maintenance date.')
    values = {
        **scope_fields(data['scope'], affected),
        'recurrence': recurring, 'start_date': first, 'end_date': last, 'selections': selected,
        'reasons': list(dict.fromkeys(reason_names)), 'description': description,
        'duration': duration, 'expected_completion': expected,
    }
    return values, affected, windows


def affected_bookings(affected, windows, catalog):
    from . import class_utilization as cu
    _, by_key, aliases = catalog
    now = local_now()
    keys = {room['key'] for room in affected}
    by_date = defaultdict(list)
    for day,start,end in windows:
        by_date[day].append((start,end))
    result = []
    bookings = ClassroomBooking.objects.filter(is_active=True, booking_date__in=by_date,
        status__in=('pending','hod_approved','confirmed','changes_requested')).select_related('booked_by')
    for booking in bookings:
        if booking.booking_date == now.date() and booking.to_time <= now.time():
            continue
        room = by_key.get(booking.room_key) or cu._resolve_room(
            {'campus_code': booking.campus_code,'building_name': booking.building_name,'room_number': booking.room_code},by_key,aliases)
        if room and room['key'] in keys and any(booking.from_time<end and booking.to_time>start for start,end in by_date[booking.booking_date]):
            result.append({'reference': booking.pk, 'date': booking.booking_date.isoformat(),
                           'start': booking.from_time.strftime('%H:%M'), 'end': booking.to_time.strftime('%H:%M'),
                           'faculty': booking.teacher_name or (booking.booked_by.get_full_name() if booking.booked_by else ''),
                           'room': room['room_name'], 'status': booking.get_status_display(),
                           'blocking': booking.status in ('hod_approved','confirmed'), 'on_hold': booking.status=='pending'})
    terms = {}
    semesters = cu._load_semester_choices()
    for day,spans in by_date.items():
        term = cu.get_current_semester(day)
        if term not in terms:
            if term not in semesters:
                raise ValueError(f'Timetable data is unavailable for {term}. Maintenance overlaps cannot be reviewed.')
            terms[term] = []
            for row in cu._load_timetable(term,by_key,aliases):
                if row['room_key'] in keys:
                    terms[term].append(row)
                elif not row['room_key']:
                    alias = (cu._normalise(row['campus']),cu._normalise(row['room_code']))
                    for key in sorted(aliases.get(alias,set()) & keys):
                        terms[term].append({**row,'room_name':by_key[key]['room_name']})
        for row in terms[term]:
            if day == now.date() and row['end_minutes'] <= cu._minutes(now.time()):
                continue
            if row['weekday']==cu.DAYS[day.weekday()] and any(row['start_minutes']<cu._minutes(end) and row['end_minutes']>cu._minutes(start) for start,end in spans):
                result.append({'reference': 'Class', 'date': day.isoformat(), 'start': row['start_time'],
                               'end': row['end_time'],'faculty': row['instructor_name'],'room': row['room_name'],
                               'status': 'Scheduled class', 'blocking': True})
    return sorted(result, key=lambda item:(item['date'],item['start'],item['room'],str(item['reference'])))


def validate_conflicts(windows, rooms, record_id):
    by_date = defaultdict(list)
    for day,start,end in windows:
        by_date[day].append((start,end))
    conflicts = active_windows(min(by_date),max(by_date)).filter(
        date__in=by_date,maintenance__rooms__room_key__in=[room['key'] for room in rooms],
    ).exclude(maintenance_id=record_id).distinct()
    for other in conflicts:
        if any(other.start<end and other.end>start for start,end in by_date[other.date]):
            raise ValueError(f'Maintenance #{other.maintenance_id} already overlaps on {other.date:%d %b %Y}.')


def snapshot(record):
    expected = record.expected_completion
    if expected and timezone.is_aware(expected):
        expected = timezone.localtime(expected)
    return {'scope':record.scope,'campus':record.campus,'building':record.building_key,'building_name':record.building_name,'floor':record.floor,
            'room':record.room_key,'room_codes':record.room_codes,'targets':record.scope_targets,'recurrence':record.recurrence,
            'booking_ids':next((entry['booking_ids'] for entry in reversed(record.history) if 'booking_ids' in entry),[]),
            'timetable_selection':next((entry['timetable_selection'] for entry in reversed(record.history) if 'timetable_selection' in entry),False),
            'start_date':record.start_date.isoformat(),'end_date':record.end_date.isoformat(),
            'selections':record.selections,'reasons':record.reasons,'description':record.description,
            'duration':record.duration,'expected_completion':expected.strftime('%Y-%m-%dT%H:%M') if expected else ''}


def history_entry(user, action, reason='', previous=None):
    return {'action':action,'by':user.get_full_name() or user.get_username(),'at':timezone.now().isoformat(),
            'reason':reason,'previous':previous}


def record_room_releases(entry, keys):
    entry['released_rooms'] = sorted(keys)
    entry['room_releases'] = [
        {'room_key': key, 'released_at': entry['at']} for key in entry['released_rooms']
    ]


def read_json(request):
    data = json.loads(request.body)
    if not isinstance(data, dict):
        raise ValueError('Invalid maintenance form.')
    return data


def review_digest(data, rooms, overlaps, added_windows=()):
    payload = {**data, 'action':'preview'}
    material = [payload, sorted(room['key'] for room in rooms), overlaps]
    if added_windows:
        material.append([[value.isoformat() for value in window] for window in added_windows])
    material = json.dumps(material, sort_keys=True)
    return sha256(material.encode()).hexdigest()


def review_overlaps(data, rooms, windows, catalog):
    from .holidays import closures_on
    overlaps = affected_bookings(rooms,windows,catalog)
    selected = data.get('booking_ids', [])
    timetable = data.get('timetable_selection') is True
    if timetable and selected and not data.get('id'):
        raise ValueError('Select available BOOK slots only.')
    if not selected and not timetable:
        return overlaps
    if data.get('scope') != 'room' or len(rooms) != 1 or not isinstance(selected,list) or any(type(pk) is not int for pk in selected):
        raise ValueError('Select approved bookings for one classroom.')
    approved = [item for item in overlaps if item['reference'] in selected and item['blocking']]
    if set(selected) != {item['reference'] for item in approved}:
        raise ValueError('Selected bookings are no longer eligible. Refresh the timetable and select them again.')
    for day,start,end in windows:
        if rooms[0].get('maintenance') or closures_on(day,rooms[0]['campus']):
            raise ValueError('This classroom is unavailable for timetable maintenance selection.')
        if timetable:
            continue
        cursor = start.strftime('%H:%M')
        for item in approved:
            if item['date'] == day.isoformat() and item['start'] <= cursor < item['end']:
                cursor = item['end']
        if cursor < end.strftime('%H:%M'):
            raise ValueError('Maintenance hours must stay within the selected approved bookings.')
    for item in approved:
        item['blocking'] = False
    if timetable:
        for item in overlaps:
            if item.get('on_hold'):
                item['blocking'] = True
    return overlaps


def edit_room_scope(record, data, catalog):
    scope = {
        'scope': record.scope, 'building': record.building_key, 'campus': record.campus,
        'floor': record.floor, 'targets': record.scope_targets,
    }
    keys = data.get('classroom_keys')
    if keys is None and data.get('classrooms_only') is True and record.scope == 'room':
        keys = data.get('targets')
    if keys is None:
        keys = list(record.rooms.values_list('room_key', flat=True))
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or not keys:
        raise ValueError('Please select at least one classroom.')
    if record.scope == 'room':
        return scope_rooms({**scope, 'targets': keys, 'floor': ''}, catalog)
    allowed = scope_rooms(scope, catalog)
    selected = [room for room in allowed if room['key'] in keys]
    if set(keys) != {room['key'] for room in selected}:
        raise ValueError('Every selected classroom must belong to the original maintenance scope.')
    return selected


def extension_schedule(record, end_text, now):
    if not isinstance(end_text, str):
        raise ValueError('Enter the new expected completion date and time.')
    completion = datetime.fromisoformat(end_text)
    if timezone.is_aware(completion):
        completion = timezone.make_naive(completion, timezone.get_current_timezone())
    last_window = record.windows.order_by('-date', '-end').first()
    if last_window is None:
        raise ValueError('There are no saved maintenance slots to extend.')
    last_end = datetime.combine(last_window.date, last_window.end)
    previous = record.expected_completion
    if previous and timezone.is_aware(previous):
        previous = timezone.make_naive(previous, timezone.get_current_timezone())
    local = now.replace(tzinfo=None)
    if completion <= max(last_end, previous or last_end, local):
        raise ValueError('Choose a completion time later than the current schedule and the current time.')
    if (completion.date() - record.start_date).days > 365:
        raise ValueError('The extended schedule must span at most 366 days.')

    windows = []
    if record.recurrence:
        rules = defaultdict(list)
        for item in record.selections:
            rules[date.fromisoformat(item['date']).weekday()].append(
                (time.fromisoformat(item['start']), time.fromisoformat(item['end'])))
        start = max(record.end_date, local.date())
        for offset in range((completion.date() - start).days + 1):
            day = start + timedelta(days=offset)
            for first, last in sorted(rules[day.weekday()]):
                if day == record.end_date:
                    if not previous or previous.date() != day:
                        continue
                    first = max(first, previous.time(), last_end.time() if last_end.date() == day else time.min)
                if day == completion.date():
                    last = min(last, completion.time())
                if first < last and datetime.combine(day, last) > local:
                    windows.append((day, first, last))
        if not windows:
            raise ValueError('The extension must include at least one scheduled weekday and time slot.')
        selections = record.selections
    else:
        first_at = max(last_end, local.replace(second=0, microsecond=0))
        for offset in range((completion.date() - first_at.date()).days + 1):
            day = first_at.date() + timedelta(days=offset)
            first = first_at.time() if day == first_at.date() else time.min
            last = completion.time() if day == completion.date() else time(23, 59)
            if first < last:
                windows.append((day, first, last))
        selections = [*record.selections, *(
            {'date': day.isoformat(), 'start': first.strftime('%H:%M'), 'end': last.strftime('%H:%M')}
            for day, first, last in windows
        )]
    expected = timezone.make_aware(completion, timezone.get_current_timezone()) if settings.USE_TZ else completion
    return {'end_date': completion.date(), 'expected_completion': expected, 'selections': selections}, windows


@admin_only
@require_POST
def schedule(request):
    from .class_utilization import _load_room_catalog
    try:
        data = read_json(request)
        record_id = data.get('id') or None
        catalog = _load_room_catalog()
        classrooms_only = data.get('classrooms_only') is True
        extending = 'extend_until' in data
        now = local_now()
        record = get_object_or_404(ClassroomMaintenance, pk=record_id, state='open') if record_id else None
        if classrooms_only or extending:
            if record is None:
                raise ValueError('Open an existing classroom maintenance record before editing classrooms.')
            rooms = edit_room_scope(record, data, catalog[0])
            values = scope_fields(record.scope, rooms)
            if record.scope == 'floor':
                values['floor'] = record.floor
                values['scope_targets'] = record.scope_targets or [record.floor]
            existing_keys = set(record.rooms.values_list('room_key', flat=True))
            added_rooms = [room for room in rooms if room['key'] not in existing_keys]
            existing_windows = list(record.windows.filter(
                Q(date__gt=now.date()) | Q(date=now.date(), end__gt=now.time())
            ).values_list('date', 'start', 'end')) if added_rooms else []
            windows = []
            if extending:
                extended_values, windows = extension_schedule(record, data['extend_until'], now)
                values.update(extended_values)
        else:
            scoped_edit = record and (data.get('classroom_keys') is not None or (
                record.scope != 'room' and record.scope == data.get('scope')
                and record.building_key == data.get('building')))
            selected_rooms = edit_room_scope(record, data, catalog[0]) if scoped_edit else None
            values, rooms, windows = parse_schedule(data, catalog[0], now=now, editing=bool(record_id),
                selected_rooms=selected_rooms,
                cap_recurrence=bool(record and any(entry.get('extended_until') for entry in record.history)))
            if scoped_edit and record.scope == 'floor':
                values['floor'] = record.floor
                values['scope_targets'] = record.scope_targets or [record.floor]

        def review_schedule():
            overlaps = []
            if windows:
                validate_conflicts(windows, rooms, record_id)
                overlaps.extend(review_overlaps({} if extending else data, rooms, windows, catalog))
            if (classrooms_only or extending) and existing_windows:
                validate_conflicts(existing_windows, added_rooms, record_id)
                overlaps.extend(review_overlaps({}, added_rooms, existing_windows, catalog))
            return overlaps

        def digest(overlaps):
            return review_digest(data, rooms, overlaps, windows if extending else ())

        if data.get('action') == 'preview':
            overlaps = review_schedule()
            signature = dumps({'user':request.user.pk,'digest':digest(overlaps),
                               'version':record.updated_at.isoformat() if record else ''},salt=SALT,compress=True)
            return JsonResponse({'token':signature,'affected':overlaps,'room_codes':values['room_codes'],
                                 'building':values['building_name'],'campus':values['campus'],'floor':values['floor'],
                                 'targets':values['scope_targets'],'blocking':any(item['blocking'] for item in overlaps),
                                 'window_count':len(windows) + (record.windows.count() if classrooms_only or extending else 0),
                                 'extension_windows': [
                                     {'date': day.isoformat(), 'start': first.strftime('%H:%M'), 'end': last.strftime('%H:%M')}
                                     for day, first, last in windows
                                 ] if extending else []})
        if data.get('action') != 'save':
            raise ValueError('Choose a valid maintenance action.')
        confirmed = loads(data.pop('token',''),salt=SALT,max_age=900)
        acknowledged = data.pop('acknowledge_overlaps', False) is True
        if confirmed['user'] != request.user.pk:
            raise ValueError('Review the updated schedule before confirming.')
        with transaction.atomic():
            lock_bookings()
            record = get_object_or_404(ClassroomMaintenance,pk=record_id,state='open') if record_id else None
            if (record.updated_at.isoformat() if record else '') != confirmed['version']:
                raise ValueError('This schedule changed. Reopen it before updating.')
            overlaps = review_schedule()
            has_conflicts = any(item['blocking'] for item in overlaps)
            if has_conflicts and not (acknowledged and not data.get('booking_ids') and not data.get('timetable_selection')):
                raise ValueError('Resolve overlapping scheduled classes and approved bookings before confirming maintenance.')
            if digest(overlaps) != confirmed['digest']:
                raise ValueError('The schedule or affected bookings changed. Review the schedule again before confirming.')
            previous = snapshot(record) if record else None
            prior_keys = set(record.rooms.values_list('room_key', flat=True)) if record else set()
            selected_keys = {room['key'] for room in rooms}
            record = record or ClassroomMaintenance(created_by=request.user)
            for field,value in values.items():
                setattr(record,field,value)
            record.updated_by = request.user
            entry = history_entry(request.user,'Edited' if previous else 'Scheduled',previous=previous)
            entry['booking_ids'] = [] if classrooms_only or extending else data.get('booking_ids', [])
            entry['timetable_selection'] = not (classrooms_only or extending) and data.get('timetable_selection') is True
            if prior_keys - selected_keys:
                record_room_releases(entry, prior_keys - selected_keys)
            if selected_keys - prior_keys:
                entry['added_rooms'] = sorted(selected_keys - prior_keys)
            if previous is None:
                first_day, first_start, _ = min(windows)
                entry['original_start'] = f'{first_day.isoformat()}T{first_start:%H:%M}'
            if extending:
                entry['extended_until'] = data['extend_until']
            if has_conflicts:
                entry['reason'] = f'Admin acknowledged {sum(item["blocking"] for item in overlaps)} overlapping classes or approved bookings.'
            record.history = [*record.history,entry]
            record.save()
            if classrooms_only or extending:
                record.rooms.exclude(room_key__in=selected_keys).delete()
                ClassroomMaintenanceRoom.objects.bulk_create(
                    ClassroomMaintenanceRoom(maintenance=record, room_key=key)
                    for key in sorted(selected_keys - prior_keys)
                )
            else:
                record.rooms.all().delete()
                record.windows.all().delete()
                ClassroomMaintenanceRoom.objects.bulk_create(ClassroomMaintenanceRoom(maintenance=record,room_key=room['key']) for room in rooms)
            if not classrooms_only or extending:
                ClassroomMaintenanceWindow.objects.bulk_create(ClassroomMaintenanceWindow(maintenance=record,date=day,start=start,end=end) for day,start,end in windows)
        return JsonResponse({'id':record.pk,'message':'Maintenance scheduled successfully!'})
    except (BadSignature, SignatureExpired):
        return JsonResponse({'error':'The review expired. Review the schedule again.'},status=409)
    except (ValueError, TypeError, KeyError) as exc:
        return JsonResponse({'error':str(exc) or 'Invalid maintenance schedule.'},status=400)
    except DatabaseError:
        return JsonResponse({'error':'Maintenance could not be verified or saved. Try again.'},status=503)


@admin_only
@require_POST
def reason(request):
    try:
        name = ' '.join(str(read_json(request).get('name') or '').split())
        if not name or len(name)>120:
            raise ValueError('Enter a reason of 1 to 120 characters.')
        existing = next((item for item in available_reasons() if item.casefold()==name.casefold()),None)
        if not existing:
            with transaction.atomic():
                lock_bookings()
                custom = ClassroomMaintenanceReason.objects.filter(name__iexact=name).first()
                existing = custom.name if custom else ClassroomMaintenanceReason.objects.create(name=name).name
        return JsonResponse({'name':existing or name})
    except (ValueError, TypeError, IntegrityError) as exc:
        return JsonResponse({'error':str(exc)},status=400)
    except DatabaseError:
        return JsonResponse({'error':'The reason could not be saved. Try again.'},status=503)


@admin_only
@require_POST
def finish(request, pk):
    try:
        data = read_json(request)
        action = data.get('action')
        if action not in ('complete','cancel','undo'):
            raise ValueError('Choose a valid maintenance action.')
        note = str(data.get('reason') or '').strip()
        if len(note)>5000:
            raise ValueError('Keep the reason within 5,000 characters.')
        with transaction.atomic():
            lock_bookings()
            record = get_object_or_404(ClassroomMaintenance,pk=pk,state='open')
            if action == 'cancel':
                first = record.windows.first()
                now = local_now()
                if first and (first.date,first.start) <= (now.date(),now.time()):
                    raise ValueError('This maintenance has started. Use End.')
            record.state = 'completed' if action=='complete' else 'cancelled'
            record.updated_by=request.user
            label = {'complete':'Completed','cancel':'Cancelled','undo':'Undone'}[action]
            record.history=[*record.history,history_entry(request.user,label,note)]
            record.save(update_fields=['state','updated_by','history','updated_at'])
        return JsonResponse({'message':f'Maintenance {label.lower()}.'})
    except (ValueError,TypeError) as exc:
        return JsonResponse({'error':str(exc)},status=400)
    except DatabaseError:
        return JsonResponse({'error':'Maintenance could not be updated. Try again.'},status=503)


@admin_only
@require_POST
def undo_floor(request):
    from .class_utilization import _load_room_catalog

    try:
        data = read_json(request)
        signed = loads(data.get('token') or '', salt=FLOOR_UNDO_SALT, max_age=900)
        if signed['user'] != request.user.pk:
            raise BadSignature
        reason = str(data.get('reason') or '').strip()
        if len(reason) > 5000:
            raise ValueError('Keep the reason within 5,000 characters.')
        rooms, rooms_by_key, _ = _load_room_catalog()
        floor_keys = {room['key'] for room in scope_rooms({**signed, 'scope': 'floor'}, rooms)}
        if floor_keys != set(signed['rooms']):
            return JsonResponse({'error': 'The classroom list changed. Reload the floor and try again.'}, status=409)
        selected = data.get('rooms')
        if not isinstance(selected, list) or not selected or any(
            not isinstance(key, str) or key not in floor_keys for key in selected
        ):
            raise ValueError('Uncheck at least one classroom on this floor to release it.')
        release_keys = set(selected)
        versions = signed['records']
        with transaction.atomic():
            lock_bookings()
            records = list(ClassroomMaintenance.objects.filter(
                pk__in=versions, state='open', building_key=signed['building'],
            ).prefetch_related('rooms'))
            if len(records) != len(versions) or any(
                record.updated_at.isoformat() != versions[str(record.pk)] for record in records
            ):
                return JsonResponse({'error': 'Maintenance changed. Reload the floor and try again.'}, status=409)
            for record in records:
                assigned = {room.room_key for room in record.rooms.all()}
                released = assigned & release_keys
                if not released:
                    continue
                remaining = assigned - released
                if not remaining.issubset(rooms_by_key):
                    raise ValueError('The classroom list changed. Reload the floor and try again.')
                previous = snapshot(record)
                if remaining:
                    remaining_rooms = [rooms_by_key[key] for key in sorted(remaining)]
                    scope = 'room'
                    if record.scope != 'room':
                        remaining_floors = {room.get('floor_code') or '__unrecorded__' for room in remaining_rooms}
                        floor_scope = scope_rooms({**signed, 'scope': 'floor', 'targets': sorted(remaining_floors)}, rooms)
                        if {room['key'] for room in floor_scope} == remaining:
                            scope = 'floor'
                    for field, value in scope_fields(scope, remaining_rooms).items():
                        setattr(record, field, value)
                    record.rooms.filter(room_key__in=released).delete()
                else:
                    record.state = 'cancelled'
                entry = history_entry(request.user, 'Classroom maintenance undone', reason, previous)
                entry['floor'] = signed['floor']
                record_room_releases(entry, released)
                record.history = [*record.history, entry]
                record.updated_by = request.user
                record.save()
        return JsonResponse({'message': 'Maintenance undone for the unchecked classrooms.'})
    except BadSignature:
        return JsonResponse({'error': 'This action expired. Reload the floor and try again.'}, status=409)
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse({'error': str(exc) or 'Invalid floor maintenance.'}, status=400)
    except DatabaseError:
        return JsonResponse({'error': 'Maintenance could not be updated. Try again.'}, status=503)


@admin_only
@require_GET
def manage(request):
    from .class_utilization import _load_room_catalog
    rooms, rooms_by_key, _ = _load_room_catalog()
    filters={field:request.GET.get(field,'').strip() for field in ('campus','building','floor','room','status','date','q')}
    queryset=ClassroomMaintenance.objects.select_related('created_by','updated_by').prefetch_related('rooms', 'windows')
    reference = request.GET.get('reference', '')
    if reference:
        queryset = queryset.filter(pk=reference) if reference.isascii() and reference.isdecimal() and len(reference) <= 18 else queryset.none()
    for field,query_field in {'campus':'campus__iexact','building':'building_key','room':'rooms__room_key'}.items():
        if filters[field]:
            queryset=queryset.filter(**{query_field:filters[field]})
    if filters['floor']:
        floor_keys = [room['key'] for room in rooms if (room.get('floor_code') or '__unrecorded__') == filters['floor']]
        queryset=queryset.filter(Q(floor=filters['floor'])|Q(rooms__room_key__in=floor_keys))
    if filters['status'] in ('completed','cancelled'):
        queryset=queryset.filter(state=filters['status'])
    elif filters['status'] == 'active':
        queryset=queryset.filter(state='open')
    if filters['date']:
        try:
            queryset=queryset.filter(windows__date=date.fromisoformat(filters['date']))
        except ValueError:
            queryset=queryset.none()
    if filters['q']:
        query=filters['q']
        conditions=Q(description__icontains=query)|Q(reasons__icontains=query)|Q(building_name__icontains=query)|Q(room_codes__icontains=query)
        if query.isdigit():
            conditions|=Q(pk=int(query))
        queryset=queryset.filter(conditions)
    page=Paginator(queryset.distinct(),25).get_page(request.GET.get('page'))
    now = local_now()
    active = window_map(now.date(), now.date(), rooms_by_key)
    rooms = [
        {**room, 'under_maintenance': bool(room['maintenance']) or any(
            window.start <= now.time() < window.end for window in active.get((room['key'], now.date()), ())
        )}
        for room in rooms
    ]
    records={}
    for record in page:
        record.display_status = maintenance_status(record, now)
        floors = [record.floor] if record.floor else []
        if record.scope == 'floor' and not floors:
            floors = record.scope_targets
        if record.scope == 'room' and not floors:
            floors = sorted({rooms_by_key.get(key, {}).get('floor_code') or '__unrecorded__'
                             for key in record.scope_targets})
        record.floor_labels = ['Not recorded' if floor == '__unrecorded__' else floor for floor in floors]
        records[record.pk]={**snapshot(record),'id':record.pk,'status':record.display_status,
                            'assigned_room_keys': [room.room_key for room in record.rooms.all()],
                            'saved_windows': [
                                {'date': window.date.isoformat(), 'start': window.start.strftime('%H:%M'),
                                 'end': window.end.strftime('%H:%M')} for window in record.windows.all()
                            ],
                            'floor_labels':record.floor_labels,
                            'history':record.history,'created_at':record.created_at,'updated_at':record.updated_at,
                            'created_by':str(record.created_by or ''),'updated_by':str(record.updated_by or '')}
    params=request.GET.copy();params.pop('page',None)
    return render(request,'workspace/classroom_maintenance.html',{'rooms':rooms,'maintenance_reasons':available_reasons(),
        'page':page,'records':records,'filters':filters,'filter_query':params.urlencode()})
