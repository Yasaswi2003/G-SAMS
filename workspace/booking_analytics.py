"""Admin-only analytics sourced from the booking and timetable databases."""
import csv
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from io import BytesIO
from urllib.parse import urlencode
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Count
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.utils import timezone
from .booking_workflow import role
from .models import ClassroomBooking as Booking, ClassroomBookingHistory


def series(qs, field):
    return [{'label': row[field] or 'Unassigned', 'value': row['total']} for row in qs.values(field).annotate(total=Count('id')).order_by('-total', field)]


def build_analytics(params, *, snapshot=False, catalog=None):
    from . import class_utilization as cu
    today = date.today()
    start = date.fromisoformat(params.get('start') or (today - timedelta(days=today.weekday())).isoformat())
    end = date.fromisoformat(params.get('end') or (start + timedelta(days=4)).isoformat())
    if end < start or (end-start).days > 365:
        raise ValueError('Choose a date range of up to 366 days.')
    qs = Booking.objects.filter(booking_date__range=(start,end), is_active=True)
    for field, lookup in [('campus','campus_code__iexact'),('department','requester_department__iexact'),('building','building_name__icontains'),('room','room_code__iexact'),('status','status')]:
        if snapshot and field in ('campus', 'building'):
            continue
        if params.get(field):
            qs = qs.filter(**{('room_key' if field=='room' and '|' in params[field] else lookup):params[field]})
    rooms, by_key, aliases = catalog if catalog is not None else cu._load_room_catalog()
    rooms = [r for r in rooms if (not params.get('campus') or cu._normalise(r['campus']) == cu._normalise(params['campus']))
             and (not params.get('building') or cu._normalise(params['building']) == cu._normalise(r['building_code'])
                  or (cu._normalise(params['building']) == cu._normalise(r['building']) if snapshot
                      else cu._normalise(params['building']) in cu._normalise(r['building'])))
             and (not params.get('room') or cu._normalise(r['room_code']) == cu._normalise(params['room']) or r['key'] == params['room'])]
    if params.get('floor'):
        rooms = [room for room in rooms if (room.get('floor_code') or '__unrecorded__') == params['floor']]
    keys = {r['key'] for r in rooms}
    def trend(counter):
        return [{'label':key,'value':counter[key]} for key in sorted(counter)]
    interval_map = defaultdict(list)
    for b in qs.filter(status='confirmed'):
        room = by_key.get(b.room_key)
        if not room:
            room = cu._resolve_room({'campus_code':b.campus_code,'building_name':b.building_name,'room_number':b.room_code},by_key,aliases)
        if room and room['key'] in keys:
            interval_map[(b.booking_date,room['key'])].append((cu._minutes(b.from_time),cu._minutes(b.to_time)))
    terms, missing_terms, workdays = {}, set(), 0
    day = start
    while day <= end:
        is_workday = day.weekday() < 5
        if (snapshot and keys) or (not snapshot and is_workday):
            workdays += is_workday
            term = cu.get_current_semester(day)
            if term not in terms:
                grouped = defaultdict(list)
                if term in cu._load_semester_choices():
                    for row in cu._load_timetable(term,by_key,aliases):
                        if row['room_key'] in keys and (not params.get('department') or cu._normalise(row['dept_code']) == cu._normalise(params['department'])):
                            grouped[row['weekday']].append(row)
                elif not snapshot:
                    raise ValueError('Utilization cannot be calculated: timetable data is missing for '+term)
                else:
                    missing_terms.add(term)
                terms[term] = grouped
            if is_workday:
                for row in terms[term][cu.DAYS[day.weekday()]]:
                    interval_map[(day,row['room_key'])].append((row['start_minutes'],row['end_minutes']))
        day += timedelta(days=1)
    from .utilization_summary import summarize_utilization
    dates = [start + timedelta(days=index) for index in range((end-start).days+1)]
    events = [{'room_key':key,'weekday':cu.DAYS[day.weekday()],'date':day.isoformat(),
               'start_minutes':a,'end_minutes':b}
              for (day,key),spans in interval_map.items() for a,b in spans]
    from .holidays import closures_on
    closed_dates = {
        campus: [day.isoformat() for day in dates if day.weekday() < 5 and closures_on(day, campus)]
        for campus in {room['campus'] for room in rooms}
    }
    closed = {(room['key'], day) for room in rooms for day in closed_dates[room['campus']]}
    utilization_summary = summarize_utilization(
        rooms, events, cu.DEFAULT_DAYS, 8, 16, dates=dates, closures=closed, include_heatmap=not snapshot,
    )
    if snapshot:
        return {
            'utilization_summary': utilization_summary,
            'missing_terms': sorted(missing_terms),
            'timetable_room_keys': {
                row['room_key'] for grouped in terms.values() for rows in grouped.values() for row in rows
            },
            'rooms_by_key': {room['key']: room for room in rooms},
        }
    counts = dict(qs.values_list('status').annotate(total=Count('id')))
    cards = [{'label':'Total Classrooms','value':len(rooms)}, {'label':'Total Booking Requests','value':qs.count()}]
    cards += [{'label':label,'value':counts.get(status,0)} for status,label in Booking.STATUS_CHOICES]
    daily, weekly, monthly = Counter(), Counter(), Counter()
    for day in qs.values_list('booking_date',flat=True):
        daily[day.isoformat()] += 1
        weekly[(day-timedelta(days=day.weekday())).isoformat()] += 1
        monthly[day.strftime('%Y-%m')] += 1
    occupied = utilization_summary['occupied_minutes']
    capacity = utilization_summary['capacity_minutes']
    utilization = round(occupied/capacity*100,2) if capacity else 0
    from .analytics_dashboard import build_dashboard
    dashboard = build_dashboard(qs, params, start, end, by_key, aliases, interval_map, workdays)
    reviewers = ClassroomBookingHistory.objects.filter(booking__in=qs,user_role='HOD',action__in=['Approved','Rejected'])
    charts = [
        {'title':'Requests by campus','data':series(qs,'campus_code')},
        {'title':'Requests by department','data':series(qs,'requester_department')},
        {'title':'Booking statuses','data':[{'label':label,'value':counts.get(value,0)} for value,label in Booking.STATUS_CHOICES]},
        {'title':'Daily booking trend','data':trend(daily)},
        {'title':'Weekly booking trend','data':trend(weekly)},
        {'title':'Monthly booking trend','data':trend(monthly)},
        {'title':'Most frequently confirmed classrooms','data':[{'label':r['campus_code']+' / '+r['building_name']+' / '+r['room_code'],'value':r['total']} for r in qs.filter(status='confirmed').values('campus_code','building_name','room_code').annotate(total=Count('id')).order_by('-total')[:15]]},
        {'title':'Classroom utilization (%)','data':[{'label':'Occupied','value':utilization},{'label':'Available','value':round(100-utilization,2) if capacity else 0}]},
        {'title':'Faculty booking activity','data':series(qs.filter(booking_source='teacher_request'),'teacher_id')},
        {'title':'HOD decisions (includes reconsiderations)','data':[{'label':str(r['performed_by__username'])+' / '+r['action'],'value':r['total']} for r in reviewers.values('performed_by__username','action').annotate(total=Count('id')).order_by('performed_by__username','action')]},
        {'title':'Admin direct vs faculty requests','data':[{'label':'Admin direct','value':qs.filter(booking_source='admin_direct').count()},{'label':'Faculty requests','value':qs.filter(booking_source='teacher_request').count()}]},
    ]
    return {'utilization_summary':utilization_summary,'dashboard':dashboard,'cards':cards,'charts':charts,'start':start.isoformat(),'end':end.isoformat(),'utilization':utilization,'occupied_hours':round(occupied/60,2),'capacity_hours':capacity/60,'metric_note':'Utilization is the union of master timetable classes and filtered confirmed bookings, Monday-Friday 08:00-16:00. Pending and rejected requests do not count as occupied. Trends use booking date.'}


def _space_rate(minutes, capacity):
    return round(minutes / capacity * 100, 1) if capacity else None


MAINTENANCE_TYPES = {
    'Civil Maintenance': 'civil',
    'Electrical Issue': 'electrical',
    'Plumbing Issue': 'plumbing',
    'Air Conditioning Not Working': 'hvac',
    'Benches / Furniture Not Available': 'furniture',
}
MAINTENANCE_STATUSES = ('Ongoing', 'Upcoming', 'Completed', 'Overdue')


def _maintenance_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, remainder = divmod(remainder, 60)
    return ' '.join(part for part in (
        f'{days} day' if days == 1 else f'{days} days' if days else '',
        f'{hours} h' if hours else '',
        f'{remainder} min' if remainder else '',
    ) if part)


def _maintenance_views(start, end, rooms, now):
    from .class_utilization import _minutes
    from .classroom_maintenance import maintenance_status
    from .models import ClassroomMaintenance, ClassroomMaintenanceRoom, ClassroomMaintenanceWindow

    range_minutes = ((end - start).days + 1) * 1440
    assignments = ClassroomMaintenanceRoom.objects.filter(room_key__in=rooms)
    overlapping_windows = ClassroomMaintenanceWindow.objects.filter(date__range=(start, end))
    records = ClassroomMaintenance.objects.exclude(state='cancelled').filter(
        pk__in=assignments.values('maintenance_id'),
    ).filter(pk__in=overlapping_windows.values('maintenance_id')).prefetch_related('rooms', 'windows')
    rows = []
    scheduled_rooms = set()
    for record in records:
        status = maintenance_status(record, now)
        types = [{'name': reason, 'colour': MAINTENANCE_TYPES.get(reason, 'other')}
                 for reason in sorted(set(filter(None, record.reasons)), key=str.casefold)]
        windows = [window for window in record.windows.all() if start <= window.date <= end]
        timeline = []
        for window in windows:
            first, last = _minutes(window.start), _minutes(window.end)
            timeline.append({
                'left': ((window.date - start).days * 1440 + first) / range_minutes * 100,
                'width': (last - first) / range_minutes * 100,
                'label': f'{window.date:%d %b %Y}, {window.start:%H:%M} to {window.end:%H:%M}',
            })
        minutes = sum(_minutes(window.end) - _minutes(window.start) for window in record.windows.all())
        for assignment in record.rooms.all():
            key = assignment.room_key
            if key not in rooms:
                continue
            scheduled_rooms.add(key)
            room = rooms[key]
            rows.append({
                'id': record.pk, 'room_key': key, 'room': room.get('room_code') or room.get('room_name'),
                'building': room['building'], 'campus': room['campus'], 'floor': room.get('floor_code') or '',
                'status': status, 'start': record.start_date, 'end': record.end_date, 'minutes': minutes,
                'duration': _maintenance_duration(minutes), 'types': types,
                'reason': ', '.join(item['name'] for item in types), 'timeline': timeline,
            })

    for key, room in rooms.items():
        if room.get('maintenance') and key not in scheduled_rooms:
            rows.append({
                'room_key': key, 'room': room.get('room_code') or room.get('room_name'),
                'building': room['building'], 'campus': room['campus'], 'floor': room.get('floor_code') or '',
                'status': 'Catalog-only', 'minutes': 0,
            })

    def natural(value):
        return tuple(int(part) if index % 2 else part.casefold()
                     for index, part in enumerate(re.split(r'([0-9]+)', value or '')))

    rows.sort(key=lambda row: (natural(row['building']), row['campus'], not row['floor'],
                               natural(row['floor']), natural(row['room']), row.get('start') or date.max))
    campuses = sorted({room['campus'] for room in rooms.values() if room['campus']})
    return [_maintenance_view(rows, '')] + [
        _maintenance_view([row for row in rows if row['campus'] == campus], campus)
        for campus in campuses
    ]


def _maintenance_view(rows, campus_filter):
    schedule_statuses = {row['id']: row['status'] for row in rows if row.get('id')}
    counts = Counter(schedule_statuses.values())

    buildings = defaultdict(list)
    for row in rows:
        if row.get('id'):
            buildings[row['campus'], row['building']].append(row)
    breakdown = []
    for (campus, building), building_rows in sorted(buildings.items()):
        rooms_by_status = defaultdict(set)
        rooms_by_type_status = defaultdict(set)
        for row in building_rows:
            rooms_by_status[row['status']].add(row['room_key'])
            for item in row['types']:
                rooms_by_type_status[item['name'], item['colour'], row['status']].add(row['room_key'])
            if not row['types']:
                rooms_by_type_status['Type not recorded', '', row['status']].add(row['room_key'])
        total = sum(map(len, rooms_by_status.values()))
        breakdown.append({
            'campus': campus, 'label': building, 'count': len({row['room_key'] for row in building_rows}),
            'segments': [{'status': status, 'count': len(keys), 'width': 100 * len(keys) / total}
                         for status, keys in rooms_by_status.items()],
            'types': [{'name': name, 'colour': colour, 'status': status, 'count': len(keys)}
                      for (name, colour, status), keys in sorted(rooms_by_type_status.items())],
        })
    return {
        'campus': campus_filter, 'rows': rows, 'scheduled': bool(buildings), 'breakdown': breakdown,
        'totals': [{'status': status, 'count': counts[status]} for status in MAINTENANCE_STATUSES],
    }


def _scoped_bookings(start, end, filters, catalog):
    from . import class_utilization as cu
    _, by_key, aliases = catalog
    for booking in Booking.objects.filter(is_active=True, booking_date__range=(start, end)):
        room = by_key.get(booking.room_key) or cu._resolve_room(
            {'campus_code': booking.campus_code, 'building_name': booking.building_name,
             'room_number': booking.room_code}, by_key, aliases,
        )
        campus = room['campus'] if room else booking.campus_code
        building = room['building'] if room else booking.building_name
        if filters['campus'] and cu._normalise(campus) != cu._normalise(filters['campus']):
            continue
        if filters['building'] and cu._normalise(filters['building']) not in {
            cu._normalise(building), cu._normalise(room['building_code']) if room else '',
        }:
            continue
        yield booking, room, building


def _booking_export_rows(bookings):
    yield ['Booking ID', 'Date', 'Building', 'Room', 'Department', 'Faculty', 'Start', 'End', 'Status']
    for booking, room, building in bookings:
        yield [booking.pk, booking.booking_date, building, room['room_name'] if room else booking.room_code,
               booking.requester_department, booking.teacher_name, booking.from_time, booking.to_time,
               booking.get_status_display()]


def _booking_workbook(bookings):
    sheet_ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    package_ns = 'http://schemas.openxmlformats.org/package/2006'
    relationships = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as workbook:
        workbook.writestr('[Content_Types].xml', f'<Types xmlns="{package_ns}/content-types">'
                           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                           '<Default Extension="xml" ContentType="application/xml"/>'
                           '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                           '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                           '</Types>')
        workbook.writestr('_rels/.rels', f'<Relationships xmlns="{package_ns}/relationships">'
                           f'<Relationship Id="rId1" Type="{relationships}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        workbook.writestr('xl/workbook.xml', f'<workbook xmlns="{sheet_ns}" xmlns:r="{relationships}">'
                           '<sheets><sheet name="Bookings" sheetId="1" r:id="rId1"/></sheets></workbook>')
        workbook.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{package_ns}/relationships">'
                           f'<Relationship Id="rId1" Type="{relationships}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        with workbook.open('xl/worksheets/sheet1.xml', 'w') as sheet:
            sheet.write(f'<worksheet xmlns="{sheet_ns}"><sheetData>'.encode())
            for row in _booking_export_rows(bookings):
                cells = []
                for value in row:
                    if isinstance(value, int):
                        cells.append(f'<c><v>{value}</v></c>')
                    else:
                        value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]', '', str(value))
                        cells.append(f'<c t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>')
                sheet.write(('<row>' + ''.join(cells) + '</row>').encode())
            sheet.write(b'</sheetData></worksheet>')
    return output.getvalue()


def _semester_to_date_range(day):
    return date(day.year, 7, 1) if day.month >= 7 else date(day.year, 1, 1), day


@login_required
@require_GET
def analytics_page(request):
    if role(request.user) != 'ADMIN':
        return HttpResponseForbidden('Only Admin can access booking analytics.')
    from . import class_utilization as cu
    now = timezone.now()
    today = timezone.localdate(now) if timezone.is_aware(now) else now.date()
    default_start, default_end = _semester_to_date_range(today)
    context = {
        'start': request.GET.get('start') or default_start.isoformat(),
        'end': request.GET.get('end') or default_end.isoformat(),
        'current_semester': cu.get_current_semester(today),
        'reporting_period': 'Semester to date',
        'scope': 'All buildings',
        'filters': {key: request.GET.get('util_' + key, '').strip() for key in ('campus', 'building')},
    }
    filters = context['filters']
    try:
        start, end = date.fromisoformat(context['start']), date.fromisoformat(context['end'])
        if not 0 <= (end - start).days <= 365:
            raise ValueError
    except ValueError:
        context['error'] = 'Choose a date range of up to 366 days, ending on or after the start date.'
        return render(request, 'workspace/booking_analytics.html', context, status=400)

    duration = (end - start).days + 1
    previous_start = start - timedelta(days=min(duration, start.toordinal() - 1))
    previous_end = start - timedelta(days=1) if previous_start < start else None
    def snapshot(first, last, location):
        return build_analytics({'start': first.isoformat(), 'end': last.isoformat(), **location},
                               snapshot=True, catalog=catalog)

    try:
        try:
            catalog = cu._load_room_catalog()
        except DatabaseError:
            catalog = [], {}, {}
            context['catalog_unavailable'] = True
        rooms, _, _ = catalog
        pairs = sorted({(room['campus'], room['building']) for room in rooms})
        context['campuses'] = sorted({campus for campus, _ in pairs})
        context['building_options'] = pairs
        context['buildings'] = sorted({name for campus, name in pairs if not filters['campus'] or campus == filters['campus']})
        if filters['building'] and filters['building'] not in context['buildings']:
            aliases = {room['building'] for room in rooms if cu._normalise(room['building_code']) == cu._normalise(filters['building'])
                       and (not filters['campus'] or room['campus'] == filters['campus'])}
            if len(aliases) == 1:
                filters['building'] = aliases.pop()
        context['scope'] = ' · '.join(filter(None, (filters['campus'], filters['building']))) or 'All buildings'
        if request.GET.get('download') == 'xlsx':
            response = HttpResponse(
                _booking_workbook(_scoped_bookings(start, end, filters, catalog)),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="booking-analytics.xlsx"'
            return response
        if request.GET.get('download') == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="booking-analytics.csv"'
            writer = csv.writer(response)
            for values in _booking_export_rows(_scoped_bookings(start, end, filters, catalog)):
                writer.writerow([("'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text)
                                 for text in map(str, values)])
            return response
        current = snapshot(start, end, filters)
        campus_snapshot = (
            snapshot(start, end, {'campus': filters['campus']}) if filters['building'] else current
        )
    except DatabaseError:
        context['error'] = 'Booking or classroom data is temporarily unavailable.'
        return render(request, 'workspace/booking_analytics.html', context, status=503)

    previous = None
    if previous_end and (previous_end - previous_start).days + 1 == duration:
        try:
            previous = snapshot(previous_start, previous_end, filters)
        except DatabaseError:
            pass

    query = request.GET.copy()
    query['start'], query['end'], query['download'] = start.isoformat(), end.isoformat(), 'xlsx'
    context['download_url'] = '?' + query.urlencode()
    summary = current['utilization_summary']
    context['period_label'] = (
        start.strftime('%d %b %Y') if start == end
        else f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
    )
    context['period_days'] = duration
    context['comparison_period'] = (
        f"{previous_start.strftime('%d %b %Y')} – {previous_end.strftime('%d %b %Y')}"
        if previous_end else None
    )
    campus_totals = defaultdict(lambda: [0, 0])
    campus_room_counts = Counter()
    for room in campus_snapshot['utilization_summary']['room_usage']:
        totals = campus_totals[room['campus']]
        totals[0] += room['minutes']
        totals[1] += room['capacity']
        campus_room_counts[room['campus']] += 1
    context['campus_utilization'] = [
        {
            'name': campus,
            'rate': _space_rate(*totals),
            'room_count': campus_room_counts[campus],
            'url': '?' + urlencode({'start': start.isoformat(), 'end': end.isoformat(), 'util_campus': campus}),
        }
        for campus, totals in sorted(campus_totals.items())
    ]
    context['campus_utilization_incomplete'] = campus_snapshot['missing_terms']
    context['missing_terms'] = current['missing_terms']
    rate = _space_rate(summary['occupied_minutes'], summary['capacity_minutes'])
    previous_summary = previous['utilization_summary'] if previous and not previous['missing_terms'] else None
    catalog_rooms = current['rooms_by_key']

    def change(value, previous_value, unit=''):
        if value is None or previous_value is None:
            return None
        delta = round(value - previous_value, 1)
        display = f'{abs(delta):g}' + unit
        return {'text': (('↑ ' if delta > 0 else '↓ ') + display if delta else 'No change')
                        + ' vs prior period',
                'direction': 'up' if delta > 0 else 'down' if delta < 0 else 'steady'}

    previous_rate = None
    if not current['missing_terms'] and previous_summary:
        previous_rate = _space_rate(previous_summary['occupied_minutes'], previous_summary['capacity_minutes'])
    if rate is None:
        utilisation_note = 'No opening hours in this period'
    elif current['missing_terms']:
        utilisation_note = 'Timetable data is incomplete'
    else:
        utilisation_note = 'Classroom utilization in the selected scope'
    campus_directory = defaultdict(list)
    for campus, building_name in sorted({(room['campus'], room['building']) for room in catalog_rooms.values()}):
        campus_directory[campus].append(building_name)
    context['campus_directory'] = campus_directory.items()
    campus_names = list(campus_directory)
    catalog_available = not context.get('catalog_unavailable')
    timetable_available = catalog_available and not current['missing_terms']
    timetable_room_keys = current['timetable_room_keys']
    with_timetable = len(timetable_room_keys)
    without_timetable = len(catalog_rooms) - with_timetable
    classroom_lists = {True: [], False: []}
    room_rates = {
        room['key']: _space_rate(room['minutes'], room['capacity'])
        for room in summary['room_usage']
    }
    utilization_rooms = []
    for room in sorted(catalog_rooms.values(), key=lambda room: (
        room['campus'], room['building'], room['room_name'].casefold(), room['key'],
    )):
        has_timetable = room['key'] in timetable_room_keys
        timetable_status = 'With timetable' if has_timetable else 'Without timetable'
        if not timetable_available:
            timetable_status = 'Timetable status unavailable'
        item = {**room, 'utilization': room_rates[room['key']], 'timetable_status': timetable_status}
        utilization_rooms.append(item)
        if timetable_available:
            classroom_lists[has_timetable].append(item)
    building_totals = defaultdict(lambda: [0, 0])
    for room in summary['room_usage']:
        totals = building_totals[room['campus'], room['building']]
        totals[0] += room['minutes']
        totals[1] += room['capacity']
    utilization_buildings = [
        {'campus': campus, 'name': building, 'utilization': _space_rate(*totals)}
        for (campus, building), totals in sorted(building_totals.items())
    ]
    context['selected_campus_buildings'] = utilization_buildings
    context['room_chart_data'] = [
        {
            'code': room['room_code'], 'name': room['room_name'], 'campus': room['campus'],
            'building': room['building'], 'rate': room['utilization'],
            'timetable': (room['key'] in timetable_room_keys) if timetable_available else None,
        }
        for room in utilization_rooms
    ]
    context['room_utilization_charts'] = [
        ('top', 'Top 5 Classrooms'),
        ('bottom', 'Bottom 5 Classrooms'),
        ('true', 'Top 5 Classrooms With Timetables'),
        ('false', 'Top 5 Classrooms Without Timetables'),
    ]
    if catalog_available:
        try:
            context['maintenance_start'] = start.isoformat()
            context['maintenance_end'] = end.isoformat()
            context['maintenance_views'] = _maintenance_views(start, end, catalog_rooms, now)
        except DatabaseError:
            context['maintenance_unavailable'] = True
    context['classroom_campuses'] = campus_names
    timetable_note = 'Timetables for academic terms in the selected dates'
    if not timetable_available:
        timetable_note = 'Classroom catalogue unavailable' if not catalog_available else 'Timetable data is incomplete'
    context['kpis'] = [
        {'label': 'Total Campuses', 'value': len(campus_names) if catalog_available else '—',
         'icon': 'bx-buildings', 'note': 'Campuses in the selected scope' if catalog_available else 'Classroom catalogue unavailable',
         'campus_directory': True},
        {'label': 'Active Classrooms With Timetables', 'value': with_timetable if timetable_available else '—',
         'icon': 'bx-calendar-check', 'note': timetable_note,
         'classroom_directory': timetable_available, 'classrooms': classroom_lists[True]},
        {'label': 'Classrooms Without Timetables', 'value': without_timetable if timetable_available else '—',
         'icon': 'bx-door-open', 'note': timetable_note,
         'classroom_directory': timetable_available, 'classrooms': classroom_lists[False]},
        {'label': 'Average Utilization', 'value': f'{rate:g}%' if rate is not None else '—', 'icon': 'bx-bar-chart-alt-2',
         'note': utilisation_note, 'meter': rate,
         'meter_label': 'Classroom utilisation', 'trend': change(rate, previous_rate, ' pp'),
         'classroom_directory': catalog_available, 'classrooms': utilization_rooms,
         'utilization_buildings': utilization_buildings, 'show_timetable_status': True},
    ]
    return render(request, 'workspace/booking_analytics.html', context)


@login_required
@require_GET
def analytics_data(request):
    if role(request.user) != 'ADMIN':
        return JsonResponse({'error':'Only Admin can access booking analytics.'},status=403)
    try:
        return JsonResponse(build_analytics(request.GET))
    except (ValueError,TypeError) as error:
        return JsonResponse({'error':str(error)},status=400)
    except DatabaseError:
        return JsonResponse({'error':'Analytics source data is unavailable. Please retry.'},status=503)
