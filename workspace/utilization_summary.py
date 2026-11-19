"""Presentation metrics from the union of scheduled room occupancy."""
from collections import defaultdict


def summarize_utilization(rooms, events, days, start_hour, end_hour, dates=None, closures=None):
    """Union occupancy, for one timetable week or dated analytics periods.

    A ranged heatmap averages each weekday over its actual occurrences; room
    capacity includes every selected working date, rather than merging weeks.
    """
    rooms_by_key = {room['key']: room for room in rooms}
    closures = set(closures or ())
    names = ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
    periods = [(day, day) for day in days] if dates is None else [
        (day.isoformat(), names[day.weekday()]) for day in dates if names[day.weekday()] in days]
    intervals = defaultdict(list)
    for event in events:
        if event['room_key'] in rooms_by_key and event['weekday'] in days:
            period = event.get('date') if dates is not None else event['weekday']
            if (event['room_key'], period) in closures:
                continue
            intervals[(event['room_key'], period)].append(
                (event['start_minutes'], event['end_minutes']))

    def occupied_minutes(ranges, start, end):
        total, last = 0, start
        for a, b in sorted(ranges):
            a, b = max(a, start), min(b, end)
            total += max(0, b - max(a, last))
            last = max(last, b)
        return total

    hours = list(range(start_hour, end_hour))
    count = len(rooms)
    heatmap, peak = [], (0, None)
    hourly_minutes = defaultdict(int)
    hourly_capacity = defaultdict(int)
    for day in days:
        cells = []
        occurrences = [period for period, weekday in periods if weekday == day]
        for hour in hours:
            minutes = sum(occupied_minutes(intervals[(key, period)], hour * 60, (hour + 1) * 60)
                          for key in rooms_by_key for period in occurrences if (key, period) not in closures)
            denominator = sum(60 for key in rooms_by_key for period in occurrences if (key, period) not in closures)
            hourly_minutes[hour] += minutes
            hourly_capacity[hour] += denominator
            value = round(minutes / denominator * 100) if denominator else 0
            cells.append({'value': value, 'level': min(5, (value + 19) // 20),
                          'hour': f'{hour:02d}:00–{hour+1:02d}:00', 'occurrences': len(occurrences)})
            if minutes > peak[0]:
                peak = (minutes, f'{hour:02d}:00–{hour + 1:02d}:00')
        heatmap.append({'day': day[:3], 'cells': cells})
    building_minutes, building_capacity = defaultdict(int), defaultdict(int)
    capacity = 0
    total, idle = 0, 0
    daily = []
    for key, room in rooms_by_key.items():
        minutes = room_capacity = 0
        for period, weekday in periods:
            if (key, period) in closures:
                continue
            start, end = start_hour * 60, end_hour * 60
            ranges = intervals[(key, period)]
            occupied = occupied_minutes(ranges, start, end)
            minutes += occupied
            room_capacity += end - start
            if dates is not None and count == 1:
                longest_start = longest_end = cursor = start
                for a, b in sorted(ranges + [(end, end)]):
                    boundary = min(a, end)
                    if boundary - cursor > longest_end - longest_start:
                        longest_start, longest_end = cursor, boundary
                    cursor = max(cursor, min(b, end))
                daily.append({'date': period, 'occupied': occupied, 'capacity': end - start,
                              'window_start': longest_start, 'window_end': longest_end})
        capacity += room_capacity
        total += minutes
        idle += minutes == 0
        building = f"{room['campus']} · {room['building']}"
        building_minutes[building] += minutes
        building_capacity[building] += room_capacity
    buildings = sorted(
        [{'label': label, 'value': round(building_minutes[label] / size * 100)
          if size else 0} for label, size in building_capacity.items()],
        key=lambda item: (-item['value'], item['label']))
    hourly = [{'label': f'{hour:02d}:00–{hour+1:02d}:00',
               'value': round(hourly_minutes[hour] / hourly_capacity[hour] * 100)}
              for hour in hours if hourly_capacity[hour]]
    return {'heatmap': heatmap, 'hours': [f'{hour}–{hour + 1}' for hour in hours], 'hourly': hourly, 'daily': daily,
            'buildings': buildings, 'idle': idle, 'peak': peak[1] or '—',
            'utilization': round(total / capacity * 100) if capacity else 0,
            'rooms': count, 'occupied_minutes': total, 'capacity_minutes': capacity}
