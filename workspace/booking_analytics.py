"""Admin-only analytics sourced from the booking and timetable databases."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Count
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.utils import timezone
from .booking_workflow import role
from .models import ClassroomBooking as Booking, ClassroomBookingHistory


def series(qs, field):
    return [{'label': row[field] or 'Unassigned', 'value': row['total']} for row in qs.values(field).annotate(total=Count('id')).order_by('-total', field)]


def build_analytics(params):
    from . import class_utilization as cu
    today = date.today()
    start = date.fromisoformat(params.get('start') or (today - timedelta(days=today.weekday())).isoformat())
    end = date.fromisoformat(params.get('end') or (start + timedelta(days=4)).isoformat())
    if end < start or (end-start).days > 365:
        raise ValueError('Choose a date range of up to 366 days.')
    qs = Booking.objects.filter(booking_date__range=(start,end), is_active=True)
    for field, lookup in [('campus','campus_code__iexact'),('department','requester_department__iexact'),('building','building_name__icontains'),('room','room_code__iexact'),('status','status')]:
        if params.get(field):
            qs = qs.filter(**{('room_key' if field=='room' and '|' in params[field] else lookup):params[field]})
    rooms, by_key, aliases = cu._load_room_catalog()
    rooms = [r for r in rooms if (not params.get('campus') or cu._normalise(r['campus']) == cu._normalise(params['campus']))
             and (not params.get('building') or cu._normalise(params['building']) in cu._normalise(r['building']) or cu._normalise(params['building']) == cu._normalise(r['building_code']))
             and (not params.get('room') or cu._normalise(r['room_code']) == cu._normalise(params['room']) or r['key'] == params['room'])]
    keys = {r['key'] for r in rooms}
    counts = dict(qs.values_list('status').annotate(total=Count('id')))
    cards = [{'label':'Total Classrooms','value':len(rooms)}, {'label':'Total Booking Requests','value':qs.count()}]
    cards += [{'label':label,'value':counts.get(status,0)} for status,label in Booking.STATUS_CHOICES]
    daily, weekly, monthly = Counter(), Counter(), Counter()
    for day in qs.values_list('booking_date',flat=True):
        daily[day.isoformat()] += 1
        weekly[(day-timedelta(days=day.weekday())).isoformat()] += 1
        monthly[day.strftime('%Y-%m')] += 1
    def trend(counter):
        return [{'label':key,'value':counter[key]} for key in sorted(counter)]
    interval_map = defaultdict(list)
    for b in qs.filter(status='confirmed'):
        room = by_key.get(b.room_key)
        if not room:
            room = cu._resolve_room({'campus_code':b.campus_code,'building_name':b.building_name,'room_number':b.room_code},by_key,aliases)
        if room and room['key'] in keys:
            interval_map[(b.booking_date,room['key'])].append((cu._minutes(b.from_time),cu._minutes(b.to_time)))
    terms, workdays = {}, 0
    day = start
    while day <= end:
        if day.weekday() < 5:
            workdays += 1
            term = cu.get_current_semester(day)
            if term not in terms:
                if term not in cu._load_semester_choices():
                    raise ValueError('Utilization cannot be calculated: timetable data is missing for '+term)
                grouped = defaultdict(list)
                for row in cu._load_timetable(term,by_key,aliases):
                    if row['room_key'] in keys and (not params.get('department') or cu._normalise(row['dept_code']) == cu._normalise(params['department'])):
                        grouped[row['weekday']].append(row)
                terms[term] = grouped
            for row in terms[term][cu.DAYS[day.weekday()]]:
                interval_map[(day,row['room_key'])].append((row['start_minutes'],row['end_minutes']))
        day += timedelta(days=1)
    from .utilization_summary import summarize_utilization
    dates = [start + timedelta(days=index) for index in range((end-start).days+1)]
    events = [{'room_key':key,'weekday':cu.DAYS[day.weekday()],'date':day.isoformat(),
               'start_minutes':a,'end_minutes':b}
              for (day,key),spans in interval_map.items() for a,b in spans]
    from .holidays import closures_on
    closed = {(room['key'], day.isoformat()) for room in rooms for day in dates
              if day.weekday() < 5 and closures_on(day, room['campus'])}
    utilization_summary = summarize_utilization(rooms, events, cu.DEFAULT_DAYS, 8, 16, dates=dates, closures=closed)
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


@login_required
@require_GET
def analytics_page(request):
    if role(request.user) != 'ADMIN':
        return HttpResponseForbidden('Only Admin can access booking analytics.')
    today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
    sources = {'teacher_request': 'Faculty requests', 'admin_direct': 'Admin direct bookings'}
    context = {'bookings': [], 'data_error': '', 'booking_statuses': Booking.STATUS_CHOICES,
               'booking_sources': sources.items()}
    try:
        start = date.fromisoformat(request.GET.get('start') or (today - timedelta(days=29)).isoformat())
        end = date.fromisoformat(request.GET.get('end') or today.isoformat())
        if end < start or (end - start).days > 365:
            raise ValueError('Choose a date range of up to 366 days, with the end on or after the start.')
    except ValueError:
        context.update(start=request.GET.get('start', ''), end=request.GET.get('end', ''),
                       data_error='Choose valid start and end dates, covering no more than 366 days.')
        return render(request, 'workspace/booking_analytics.html', context, status=400)
    context.update(start=start.isoformat(), end=end.isoformat())
    try:
        from . import class_utilization as cu
        try:
            _, by_key, aliases = cu._load_room_catalog()
        except DatabaseError:
            by_key, aliases = {}, {}
            context['data_error'] = 'Room master is unavailable. Unmatched room types are shown as Unclassified.'
        # Cross-filters are intentionally NOT applied here: the browser needs all
        # rows in the range to retain the other segments of a selected chart.
        rows = Booking.objects.filter(is_active=True, booking_date__range=(start, end)).order_by('-created_at', '-pk')
        for booking in rows:
            room = by_key.get(booking.room_key) or cu._resolve_room(
                {'campus_code': booking.campus_code, 'building_name': booking.building_name,
                 'room_number': booking.room_code}, by_key, aliases)
            ends_at = datetime.combine(booking.booking_date, booking.to_time)
            if timezone.is_naive(ends_at):
                ends_at = timezone.make_aware(ends_at, timezone.get_default_timezone())
            context['bookings'].append({
                'id': booking.pk, 'date': booking.booking_date.isoformat(),
                'weekday': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[booking.booking_date.weekday()],
                'hour': booking.from_time.hour, 'department': booking.requester_department or 'Unassigned',
                'room_name': room['room_name'] if room else booking.room_code,
                'room_key': room['key'] if room else booking.room_key or cu._room_key_value(booking.campus_code, booking.building_name, booking.room_code),
                'room_code': room['room_code'] if room else booking.room_code,
                'campus': room['campus'] if room else booking.campus_code,
                'building': room['building'] if room else booking.building_name,
                'source': booking.booking_source, 'source_label': sources.get(booking.booking_source, booking.booking_source),
                'room_type': room['room_type_label'] if room else 'Unclassified',
                'status': booking.status, 'status_label': booking.get_status_display(),
                'faculty_name': booking.teacher_name or 'Unassigned',
                'created_at': booking.created_at.isoformat(),
                'time': booking.from_time.strftime('%H:%M'),
                'end_time': booking.to_time.strftime('%H:%M'), 'ends_at': ends_at.isoformat(),
            })
    except DatabaseError:
        context['bookings'] = []
        context['data_error'] = 'Booking data is unavailable. Please try Refresh again.'
        return render(request, 'workspace/booking_analytics.html', context, status=503)
    util_filters = {field: request.GET.get('util_' + field, '').strip() for field in ('campus','building','room')}
    context['util_filters'] = util_filters
    catalog = list(by_key.values())
    context['util_options'] = {
        'rooms':[{'key':r['key'],'name':r['room_name'],'code':r['room_code'],'campus':r['campus'],'building':r['building']} for r in catalog],
        'campuses':sorted({r['campus'] for r in catalog}),
        'buildings':sorted({r['building'] for r in catalog if not util_filters['campus'] or r['campus']==util_filters['campus']}),
        'classrooms':[r for r in catalog if (not util_filters['campus'] or r['campus']==util_filters['campus'])
                      and (not util_filters['building'] or r['building']==util_filters['building'])],
    }
    try:
        # Reuse the existing service and its single occupancy-union calculation.
        context['design_summary'] = build_analytics({'start':start.isoformat(),'end':end.isoformat(),**util_filters})['utilization_summary']
    except (ValueError, DatabaseError) as error:
        context['utilization_error'] = str(error) if isinstance(error, ValueError) else 'Utilization data is unavailable. Please try again.'
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
