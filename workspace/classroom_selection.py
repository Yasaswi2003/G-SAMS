"""Progressive room-master selection, reusing timetable occupancy and bookings."""
from collections import defaultdict
from django.utils import timezone
from .models import ClassroomBooking
from .holidays import closures_on


def selection_context(request, rooms, schedules, filters, today, *, partially_booked=(), maintenance_windows=None, grid_hours=(8,16)):
    from .classroom_maintenance import covers_full_day
    def link(**updates):
        query = request.GET.copy()
        query.pop('booking_id', None)
        query.pop('export', None)
        for key,value in updates.items():
            if value is None:query.pop(key,None)
            else:query[key]=value
        return '?' + query.urlencode()

    campus,building,floor = (filters['selected_campus'],filters['selected_building'],filters['selected_floor'])
    selected = next((room for room in rooms if room['key']==filters['selected_room_key']),None)
    candidates = [room for room in rooms if room['campus_key']==campus and room['building_key']==building
                  and (room.get('floor_code','') or '__unrecorded__')==floor] if campus and building and floor else []
    now = timezone.localtime() if timezone.is_aware(timezone.now()) else timezone.now()
    minute = now.hour*60+now.minute
    by_room = defaultdict(list)
    for (room_key, _), windows in (maintenance_windows or {}).items():
        by_room[room_key].extend(window for window in windows
                                 if window.date > today or window.date == today and window.end > now.time())
    held = list(ClassroomBooking.objects.filter(is_active=True,booking_date=today,
        from_time__lte=now.time().replace(tzinfo=None),to_time__gt=now.time().replace(tzinfo=None),
        status__in=['pending','hod_approved','confirmed']).values('room_key','campus_code','building_name','room_code','status')) if candidates else []
    cards=[]
    for room in candidates:
        bookings=[b for b in held if b['room_key']==room['key'] or
                  (b['campus_code'].upper()==room['campus'].upper() and b['room_code']==room['room_code']
                   and b['building_name'] in (room['building'],room['building_code']))]
        occupied=any(row['room_key']==room['key'] and row['weekday']==today.strftime('%A')
                     and row['start_minutes']<=minute<row['end_minutes'] for row in schedules)
        if room.get('maintenance'):state,label='maintenance','Maintenance'
        elif closures_on(today,room['campus']):state,label='maintenance','Public holiday'
        elif occupied or any(b['status'] in ('hod_approved','confirmed') for b in bookings):state,label='occupied','Occupied now'
        elif bookings:state,label='reserved','On hold now'
        else:state,label='available','Available now'
        if state != 'maintenance' and room['key'] in partially_booked:
            label = 'Partially booked' if state == 'available' else f'Partially booked · {label}'
            state = 'partial'
        room_maintenance = by_room.get(room['key'], ())
        if room_maintenance and not room.get('maintenance'):
            full_day = covers_full_day(room_maintenance,*grid_hours)
            state = 'maintenance' if full_day else 'partial-maintenance'
            label = 'Under Maintenance' if full_day else 'Partially Under Maintenance'
        hint = ''
        if room_maintenance:
            window = min(room_maintenance,key=lambda item:(item.date,item.start))
            record = window.maintenance
            hint = (f'{label}\n{", ".join(record.reasons)}\n'
                    f'{window.date:%A, %d %b} · {window.start:%H:%M}–{window.end:%H:%M}')
            if len(room_maintenance)>1:
                hint += '\nOpen the timetable to see all maintenance windows.'
        cards.append({**room,'state':state,'state_label':label,'floor_label':room.get('floor_code') or 'Not recorded',
                      'maintenance_hint':hint,
                      'url':link(campus=room['campus'],building=room['building_key'],floor=room.get('floor_code') or '__unrecorded__',room=room['key'])})
    floor_cards = [{**choice,'url':link(floor=choice['key'],room=''),
                    'room_count':sum(1 for room in rooms if room['campus_key']==campus and room['building_key']==building
                                     and (room.get('floor_code','') or '__unrecorded__')==choice['key'])}
                   for choice in filters['floor_choices']]
    step = 5 if selected else 4 if floor else 3 if building else 2 if campus else 1
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
            'classroom_cards':cards,'selected_classroom':selected,
            'back_to_classrooms_url':link(room='',booking_id=None),
            'selection_step':5 if selected else 4 if floor else 3 if building else 2 if campus else 1,
            'availability_timestamp':now.strftime('%d %b %Y, %H:%M')}
