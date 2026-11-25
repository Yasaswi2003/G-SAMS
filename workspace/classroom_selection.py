"""Progressive room-master selection, reusing timetable occupancy and bookings."""
from collections import defaultdict
from django.utils import timezone
from .models import ClassroomBooking
from .holidays import closures_on


def maintenance_status(windows, full_day, *, details, full_day_label='Under Maintenance'):
    state, label = ('maintenance', full_day_label) if full_day else (
        'partial-maintenance', 'Partially Under Maintenance')
    first = min(windows, key=lambda window: (window.date, window.start))
    hint = (f'{label}\n{", ".join(first.maintenance.reasons)}\n'
            f'{first.date:%A, %d %b} · {first.start:%H:%M}–{first.end:%H:%M}')
    if len(windows) > 1:
        hint += f'\n{details}'
    return state, label, hint


def selection_context(request, rooms, schedules, filters, today, *, partially_booked=(), maintenance_windows=None,
                      maintenance_date=None, grid_hours=(8,16)):
    from .classroom_maintenance import covers_full_day
    def link(**updates):
        query = request.GET.copy()
        query.pop('booking_id', None)
        query.pop('maintenance_focus', None)
        query.pop('export', None)
        for key,value in updates.items():
            if value is None:query.pop(key,None)
            else:query[key]=value
        return '?' + query.urlencode()

    campus,building,floor = (filters['selected_campus'],filters['selected_building'],filters['selected_floor'])
    selected = next((room for room in rooms if room['key']==filters['selected_room_key']),None)
    rooms_by_floor = defaultdict(list)
    for room in rooms:
        if room['campus_key'] == campus and room['building_key'] == building:
            rooms_by_floor[room.get('floor_code') or '__unrecorded__'].append(room)
    candidates = rooms_by_floor.get(floor, ())
    now = timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
    minute = now.hour*60+now.minute
    by_room = defaultdict(list)
    maintenance_date = maintenance_date or today
    for (room_key, day), windows in (maintenance_windows or {}).items():
        if day == maintenance_date:
            by_room[room_key].extend(window for window in windows
                                     if day != today or window.end > now.time())
    held = list(ClassroomBooking.objects.filter(is_active=True,booking_date=today,
        from_time__lte=now.time().replace(tzinfo=None),to_time__gt=now.time().replace(tzinfo=None),
        status__in=['pending','hod_approved','confirmed']).values('room_key','campus_code','building_name','room_code','status')) if candidates else []
    weekday = today.strftime('%A')
    occupied_now = {row['room_key'] for row in schedules
                    if row['weekday'] == weekday and row['start_minutes'] <= minute < row['end_minutes']} if candidates else set()
    cards=[]
    for room in candidates:
        bookings=[b for b in held if b['room_key']==room['key'] or
                  (b['campus_code'].upper()==room['campus'].upper() and b['room_code']==room['room_code']
                   and b['building_name'] in (room['building'],room['building_code']))]
        occupied = room['key'] in occupied_now
        if room.get('maintenance'):state,label='maintenance','Maintenance'
        elif closures_on(today,room['campus']):state,label='maintenance','Public holiday'
        elif occupied or any(b['status'] in ('hod_approved','confirmed') for b in bookings):state,label='occupied','Occupied now'
        elif bookings:state,label='reserved','On hold now'
        else:state,label='available','Available now'
        if state != 'maintenance' and room['key'] in partially_booked:
            label = 'Partially booked' if state == 'available' else f'Partially booked · {label}'
            state = 'partial'
        room_maintenance = by_room.get(room['key'], ())
        hint = ''
        if room_maintenance:
            state, label, hint = maintenance_status(
                room_maintenance, room.get('maintenance') or covers_full_day(room_maintenance, *grid_hours),
                details='Open the timetable to see all maintenance windows.',
                full_day_label='Maintenance' if room.get('maintenance') else 'Under Maintenance',
            )
        cards.append({**room,'state':state,'state_label':label,'floor_label':room.get('floor_code') or 'Not recorded',
                      'maintenance_hint':hint,
                      'url':link(campus=room['campus'],building=room['building_key'],floor=room.get('floor_code') or '__unrecorded__',room=room['key'])})
    floor_cards = []
    floor_undo_records = {}
    for choice in filters['floor_choices']:
        floor_rooms = rooms_by_floor[choice['key']]
        card = {**choice, 'url': link(floor=choice['key'], room=''), 'room_count': len(floor_rooms)}
        windows_by_date = defaultdict(lambda: defaultdict(list))
        floor_windows = {}
        for room in floor_rooms:
            for window in by_room.get(room['key'], ()):
                windows_by_date[window.date][room['key']].append(window)
                floor_windows[window.pk] = window
        full_days = {
            day for day, room_windows in windows_by_date.items()
            if len(room_windows) == len(floor_rooms) and
            all(covers_full_day(windows, *grid_hours) for windows in room_windows.values())
        }
        if floor_windows:
            card['state'], card['state_label'], card['maintenance_hint'] = maintenance_status(
                floor_windows.values(), bool(full_days), details='Open a classroom timetable to see all maintenance windows.',
                full_day_label='Entire Floor Under Maintenance',
            )
        elif any(room.get('maintenance') for room in floor_rooms):
            full_floor = all(room.get('maintenance') for room in floor_rooms)
            card.update(state='maintenance' if full_floor else 'partial-maintenance',
                        state_label='Entire Floor Under Maintenance' if full_floor else 'Partially Under Maintenance')
        if choice['key'] == floor:
            floor_undo_records = {
                window.maintenance_id: window.maintenance.updated_at.isoformat()
                for window in floor_windows.values() if window.date in full_days
                and window.start.hour < grid_hours[1]
                and (window.end.hour, window.end.minute) > (grid_hours[0], 0)
            }
        floor_cards.append(card)
    step = 5 if selected else 4 if floor else 3 if campus and building else 2 if campus else 1
    campus_cards=[]
    for choice in filters['campuses']:
        scoped=[room for room in rooms if room['campus_key']==choice['key']]
        campus_cards.append({**choice,'room_count':len(scoped),'building_count':len({room['building_key'] for room in scoped}),
            'url':link(campus=choice['key'],building='',floor='',room='')})
    building_cards=[{**choice,'room_count':sum(room['building_key']==choice['key'] for room in rooms),
                     'url':link(building=choice['key'],floor='',room='')} for choice in filters['buildings']]
    progress=[{'number':number,'label':label,'current':number==step,'complete':number<step}
              for number,label in enumerate(['Campus','Building','Floor','Classroom','Weekly timetable'],1)]
    return {'campus_cards':campus_cards,'building_cards':building_cards,'selection_progress':progress,
            'floor_cards':floor_cards,'back_to_floors_url':link(floor='',room=''),
            'floor_undo_records':floor_undo_records,
            'classroom_cards':cards,'selected_classroom':selected,
            'back_to_classrooms_url':link(room='',booking_id=None),
            'selection_step':step,
            'maintenance_date':maintenance_date,
            'availability_timestamp':now.strftime('%d %b %Y, %H:%M')}
