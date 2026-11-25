"""Presentation metrics from the union of scheduled room occupancy."""
from collections import Counter, defaultdict


def occupied_minutes(ranges, start, end):
    total, last = 0, start
    for a, b in sorted(ranges):
        a, b = max(a, start), min(b, end)
        total += max(0, b - max(a, last))
        last = max(last, b)
    return total


def summarize_weekly_snapshot(rooms, dates, terms, bookings, closed_dates, semester_for_date, days, start_hour, end_hour):
    """Calculate dated occupancy from recurring weekly schedules and booking exceptions."""
    rooms_by_key = {room['key']: room for room in rooms}
    room_counts = Counter(room['campus'] for room in rooms_by_key.values())
    closed_dates = {campus: set(values) for campus, values in closed_dates.items()}
    start, end = start_hour * 60, end_hour * 60
    working_dates = [day for day in dates if day.weekday() < 5]
    open_periods, campus_days = Counter(), Counter()
    for day in working_dates:
        term, weekday, period = semester_for_date(day), days[day.weekday()], day.isoformat()
        for campus in room_counts:
            if period not in closed_dates[campus]:
                open_periods[(term, weekday, campus)] += 1
                campus_days[campus] += 1

    weekly = defaultdict(list)
    for term, grouped in terms.items():
        for weekday, rows in grouped.items():
            for row in rows:
                weekly[(term, weekday, row['room_key'])].append((row['start_minutes'], row['end_minutes']))
    scheduled, room_minutes = {}, defaultdict(int)
    daily_scheduled = defaultdict(lambda: [0, 0])
    for (term, weekday, key), ranges in weekly.items():
        campus = rooms_by_key[key]['campus']
        occupied = occupied_minutes(ranges, start, end)
        scheduled[(term, weekday, key)] = occupied
        room_minutes[key] += occupied * open_periods[(term, weekday, campus)]
        totals = daily_scheduled[(term, weekday, campus)]
        totals[0] += occupied
        totals[1] += bool(occupied)

    daily_totals = {}
    for day in working_dates:
        term, weekday, period = semester_for_date(day), days[day.weekday()], day.isoformat()
        totals = {'minutes': 0, 'capacity': 0, 'active_rooms': 0}
        open_rooms = 0
        for campus, count in room_counts.items():
            if period in closed_dates[campus]:
                continue
            open_rooms += count
            totals['capacity'] += count * (end - start)
            occupied, active = daily_scheduled[(term, weekday, campus)]
            totals['minutes'] += occupied
            totals['active_rooms'] += active
        if open_rooms:
            daily_totals[period] = totals

    for (day, key), ranges in bookings.items():
        if day.weekday() >= 5 or key not in rooms_by_key:
            continue
        room = rooms_by_key[key]
        period = day.isoformat()
        if period in closed_dates[room['campus']]:
            continue
        weekly_key = (semester_for_date(day), days[day.weekday()], key)
        before = scheduled.get(weekly_key, 0)
        after = occupied_minutes([*weekly.get(weekly_key, ()), *ranges], start, end)
        room_minutes[key] += after - before
        daily_totals[period]['minutes'] += after - before
        daily_totals[period]['active_rooms'] += bool(after) - bool(before)

    room_usage, building_minutes, building_capacity = [], defaultdict(int), defaultdict(int)
    for key, room in rooms_by_key.items():
        minutes = room_minutes[key]
        capacity = campus_days[room['campus']] * (end - start)
        room_usage.append({
            'key': key, 'name': room.get('room_name') or room.get('room_code') or key,
            'campus': room['campus'], 'building': room['building'], 'minutes': minutes,
            'capacity': capacity, 'percent': round(minutes / capacity * 100) if capacity else None,
        })
        building = room['campus'], room['building']
        building_minutes[building] += minutes
        building_capacity[building] += capacity
    buildings = sorted(
        [{'label': f'{campus} · {building}', 'campus': campus, 'building': building,
          'value': round(building_minutes[campus, building] / size * 100) if size else 0}
         for (campus, building), size in building_capacity.items()],
        key=lambda item: (-item['value'], item['label']))
    total = sum(room['minutes'] for room in room_usage)
    capacity = sum(room['capacity'] for room in room_usage)
    return {'heatmap': [], 'hours': [f'{hour}–{hour + 1}' for hour in range(start_hour, end_hour)],
            'hourly': [], 'daily': [], 'buildings': buildings,
            'idle': sum(room['minutes'] == 0 for room in room_usage), 'peak': '—',
            'utilization': round(total / capacity * 100) if capacity else 0,
            'rooms': len(rooms), 'room_usage': room_usage, 'daily_totals': daily_totals,
            'occupied_minutes': total, 'capacity_minutes': capacity}


def summarize_utilization(rooms, events, days, start_hour, end_hour, dates=None, closures=None, *, include_heatmap=True, period_intervals=None):
    """Union occupancy, for one timetable week or dated analytics periods.

    A ranged heatmap averages each weekday over its actual occurrences; room
    capacity includes every selected working date, rather than merging weeks.
    period_intervals, when supplied, contains already-filtered room/period spans.
    """
    rooms_by_key = {room['key']: room for room in rooms}
    closures = set(closures or ())
    names = ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
    periods = [(day, day) for day in days] if dates is None else [
        (day.isoformat(), names[day.weekday()]) for day in dates if names[day.weekday()] in days]
    intervals = defaultdict(list)
    if period_intervals is not None:
        intervals.update(period_intervals)
    else:
        for event in events:
            if event['room_key'] in rooms_by_key and event['weekday'] in days:
                period = event.get('date') if dates is not None else event['weekday']
                if (event['room_key'], period) in closures:
                    continue
                intervals[(event['room_key'], period)].append(
                    (event['start_minutes'], event['end_minutes']))

    hours = list(range(start_hour, end_hour))
    count = len(rooms)
    heatmap, peak = [], (0, None)
    hourly_minutes = defaultdict(int)
    hourly_capacity = defaultdict(int)
    hourly_occupancy_cache = {}
    for day in days if include_heatmap else ():
        cells = []
        occurrences = [period for period, weekday in periods if weekday == day]
        open_periods = [(key, period) for key in rooms_by_key for period in occurrences
                        if (key, period) not in closures]
        active_rooms = {key for key, _ in open_periods}
        occupied_periods = Counter(tuple(intervals[pair]) for pair in open_periods if intervals.get(pair))
        seats = sum(rooms_by_key[key].get('capacity') or 0 for key in active_rooms)
        denominator = len(open_periods) * 60
        for hour in hours:
            minutes = 0
            for ranges, occurrences_count in occupied_periods.items():
                cache_key = ranges, hour
                if cache_key not in hourly_occupancy_cache:
                    hourly_occupancy_cache[cache_key] = occupied_minutes(ranges, hour * 60, (hour + 1) * 60)
                minutes += occurrences_count * hourly_occupancy_cache[cache_key]
            hourly_minutes[hour] += minutes
            hourly_capacity[hour] += denominator
            value = round(minutes / denominator * 100) if denominator else 0
            cells.append({'value': value, 'level': min(5, (value + 19) // 20),
                          'active_rooms': len(active_rooms), 'seats': seats, 'start_hour': hour,
                          'hour': f'{hour:02d}:00–{hour+1:02d}:00', 'occurrences': len(occurrences)})
            if minutes > peak[0]:
                peak = (minutes, f'{hour:02d}:00–{hour + 1:02d}:00')
        heatmap.append({'day': day[:3], 'cells': cells})
    building_minutes, building_capacity = defaultdict(int), defaultdict(int)
    capacity = 0
    total, idle = 0, 0
    daily, room_usage = [], []
    daily_totals = defaultdict(lambda: {'minutes': 0, 'capacity': 0, 'active_rooms': 0})
    occupancy_cache = {}
    start, end = start_hour * 60, end_hour * 60
    for key, room in rooms_by_key.items():
        minutes = room_capacity = 0
        for period, weekday in periods:
            if (key, period) in closures:
                continue
            ranges = intervals.get((key, period), ())
            cache_key = tuple(ranges)
            if cache_key not in occupancy_cache:
                occupancy_cache[cache_key] = occupied_minutes(cache_key, start, end)
            occupied = occupancy_cache[cache_key]
            daily_totals[period]['minutes'] += occupied
            daily_totals[period]['capacity'] += end - start
            daily_totals[period]['active_rooms'] += bool(occupied)
            minutes += occupied
            room_capacity += end - start
            if dates is not None and count == 1:
                longest_start = longest_end = cursor = start
                for a, b in sorted([*ranges, (end, end)]):
                    boundary = min(a, end)
                    if boundary - cursor > longest_end - longest_start:
                        longest_start, longest_end = cursor, boundary
                    cursor = max(cursor, min(b, end))
                daily.append({'date': period, 'occupied': occupied, 'capacity': end - start,
                              'window_start': longest_start, 'window_end': longest_end})
        capacity += room_capacity
        total += minutes
        idle += minutes == 0
        room_usage.append({
            'key': key,
            'name': room.get('room_name') or room.get('room_code') or key,
            'campus': room['campus'], 'building': room['building'],
            'minutes': minutes, 'capacity': room_capacity,
            'percent': round(minutes / room_capacity * 100) if room_capacity else None,
        })
        building = room['campus'], room['building']
        building_minutes[building] += minutes
        building_capacity[building] += room_capacity
    buildings = sorted(
        [{'label': f'{campus} · {building}', 'campus': campus, 'building': building,
          'value': round(building_minutes[campus, building] / size * 100) if size else 0}
         for (campus, building), size in building_capacity.items()],
        key=lambda item: (-item['value'], item['label']))
    hourly = [{'label': f'{hour:02d}:00–{hour+1:02d}:00',
               'value': round(hourly_minutes[hour] / hourly_capacity[hour] * 100)}
              for hour in hours if hourly_capacity[hour]]
    return {'heatmap': heatmap, 'hours': [f'{hour}–{hour + 1}' for hour in hours], 'hourly': hourly, 'daily': daily,
            'buildings': buildings, 'idle': idle, 'peak': peak[1] or '—',
            'utilization': round(total / capacity * 100) if capacity else 0,
            'rooms': count, 'room_usage': room_usage, 'daily_totals': dict(daily_totals),
            'occupied_minutes': total, 'capacity_minutes': capacity}
