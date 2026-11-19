"""Booking Analytics presentation data; no changes to booking decisions."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from django.utils import timezone
from .models import ClassroomBooking as Booking, ClassroomBookingHistory


def build_dashboard(qs, params, start, end, by_key, aliases, intervals, workdays):
    from . import class_utilization as cu
    bookings = list(qs)
    days = (end - start).days + 1
    prior_start, prior_end = start - timedelta(days=days), start - timedelta(days=1)
    previous = Booking.objects.filter(is_active=True, booking_date__range=(prior_start, prior_end))
    for field, lookup in [('campus', 'campus_code__iexact'), ('department', 'requester_department__iexact'),
                          ('building', 'building_name__icontains'), ('room', 'room_code__iexact'), ('status', 'status')]:
        if params.get(field):
            previous = previous.filter(**{lookup: params[field]})
    previous = list(previous)

    def metrics(rows):
        approved = sum(row.status == 'confirmed' for row in rows)
        decided = sum(row.status in ('confirmed', 'hod_rejected', 'admin_rejected') for row in rows)
        lead = [(row.booking_date - row.created_at.date()).days for row in rows if row.created_at]
        return len(rows), approved / decided * 100 if decided else None, sum(lead) / len(lead) if lead else None

    current_values, old_values = metrics(bookings), metrics(previous)
    bucket_size = 1
    trend = []
    current_counts = Counter(row.booking_date for row in bookings)
    previous_counts = Counter(row.booking_date for row in previous)
    for offset in range(0, days, bucket_size):
        size = min(bucket_size, days - offset)
        trend.append({'label': (start + timedelta(days=offset)).isoformat(),
                      'previous_label': (prior_start + timedelta(days=offset)).isoformat(),
                      'value': sum(current_counts[start + timedelta(days=offset+i)] for i in range(size)),
                      'previous': sum(previous_counts[prior_start + timedelta(days=offset+i)] for i in range(size))})

    types, weekday_types, room_counts, room_details, peak_hours = Counter(), defaultdict(Counter), Counter(), {}, Counter()
    for row in bookings:
        room = by_key.get(row.room_key) or cu._resolve_room(
            {'campus_code': row.campus_code, 'building_name': row.building_name, 'room_number': row.room_code}, by_key, aliases)
        room_type = room['room_type_label'] if room else 'Unclassified'
        types[room_type] += 1
        weekday_types[row.booking_date.weekday()][room_type] += 1
        key = room['key'] if room else (row.campus_code, row.building_name, row.room_code)
        room_counts[key] += 1
        room_details[key] = {'label': row.room_code, 'building': row.building_name, 'campus': row.campus_code}
        if row.status == 'confirmed':
            for hour in range(row.from_time.hour, 24):
                overlap = max(0, min(cu._minutes(row.to_time), (hour+1)*60) - max(cu._minutes(row.from_time), hour*60))
                peak_hours[hour] += overlap

    def occupied(key):
        minutes = 0
        for (day, room_key), spans in intervals.items():
            if room_key != key or day.weekday() >= 5:
                continue
            last = 480
            for a, b in sorted(spans):
                a, b = max(a, 480), min(b, 960)
                minutes += max(0, b - max(last, a))
                last = max(last, b)
        return round(minutes / (workdays * 480) * 100) if workdays else None

    top_rooms = [{**room_details[key], 'value': count, 'utilization': occupied(key)}
                 for key, count in room_counts.most_common(5)]
    categories = [label for label, count in types.most_common(4)]
    if len(types) > 4:
        categories.append('Other')
    weekday = []
    for index, label in enumerate(('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')):
        values = [sum(count for category, count in weekday_types[index].items() if category not in categories)
                  if category == 'Other' else weekday_types[index][category] for category in categories]
        weekday.append({'label': label, 'values': values})

    reviewed_ids = set(ClassroomBookingHistory.objects.filter(
        booking__in=qs, action__in=('Approved', 'Rejected', 'Confirmed')).values_list('booking_id', flat=True))
    reviewed = sum(row.status in ('hod_approved', 'hod_rejected', 'admin_rejected', 'confirmed', 'cancelled')
                   or row.pk in reviewed_ids for row in bookings)
    now = timezone.localtime().replace(tzinfo=None) if timezone.is_aware(timezone.now()) else timezone.now()
    completed = sum(row.status == 'confirmed' and datetime.combine(row.booking_date, row.to_time) < now for row in bookings)
    approved = sum(row.status == 'confirmed' for row in bookings)
    funnel = [{'label': label, 'value': value} for label, value in
              [('Submitted', len(bookings)), ('Reviewed', reviewed), ('Confirmed', approved), ('Completed schedule', completed)]]
    for index, item in enumerate(funnel):
        denominator = funnel[index-1]['value'] if index else 0
        item['rate'] = round(item['value'] / denominator * 100) if denominator else None

    peak = max(peak_hours, key=peak_hours.get) if any(peak_hours.values()) else None
    peak_label = f'{peak % 12 or 12} {"AM" if peak < 12 else "PM"}' if peak is not None else '—'
    cards = []
    for index, (label, unit, note) in enumerate([
        ('Total Bookings', '', 'Requests in selected booking dates'),
        ('Approval Rate', '%', 'Confirmed / confirmed and rejected'),
        ('Avg Lead Time', ' days', 'Submission date to booking date'),
    ]):
        value, old = current_values[index], old_values[index]
        delta = None if value is None or old is None or old == 0 else round((value-old)/abs(old)*100, 1)
        display = '—' if value is None else (value if index == 0 else f'{value:.1f}{unit}')
        sparkline = []
        for offset in range(0, days, bucket_size):
            lower = start + timedelta(days=offset)
            upper = min(end, lower + timedelta(days=bucket_size-1))
            sparkline.append(metrics([row for row in bookings if lower <= row.booking_date <= upper])[index])
        cards.append({'label': label, 'value': display, 'numeric_value': value,
                      'previous_value': old, 'delta': delta, 'note': note, 'series': sparkline})
    cards.append({'label': 'Peak Hour', 'value': peak_label, 'delta': None, 'note': 'Confirmed booking hours',
                  'hourly': [peak_hours[hour] for hour in range(8, 22)]})
    return {'cards': cards, 'trend': trend, 'departments': [{'label': label or 'Unassigned', 'value': count}
            for label, count in Counter(row.requester_department for row in bookings).most_common()],
            'categories': categories, 'weekday': weekday, 'top_rooms': top_rooms, 'funnel': funnel,
            'previous_start': prior_start.isoformat(), 'previous_end': prior_end.isoformat(),
            'notes': 'Compared with the preceding equal-length period. Completed schedule means a confirmed booking whose end time has passed; attendance is not tracked. Room utilization includes timetable classes and confirmed bookings, weekdays 08:00–16:00.'}
