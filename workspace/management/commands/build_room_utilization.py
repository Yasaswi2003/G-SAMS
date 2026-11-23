import csv
import json
import re
from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.core.management.base import BaseCommand, CommandError

from workspace import class_utilization as utilization
from workspace.room_utilization import DATA_PATH


def records(rows):
    headers = next(rows, None)
    if not headers:
        raise ValueError('The source file has no header row.')
    keys = [re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_') for value in headers]
    return (dict(zip(keys, row)) for row in rows if any(value is not None and value != '' for value in row))


def field(record, *names):
    return next((record[name] for name in names if record.get(name) is not None and record[name] != ''), '')


def room_record(row):
    return {
        'campus_code': field(row, 'campus_code', 'campus'),
        'building_code': field(row, 'building_code'),
        'building_name': field(row, 'building_name', 'building'),
        'room_code': field(row, 'room_code', 'room', 'room_id', 'room_number', 'room_no'),
        'room_number': field(row, 'room_number', 'room_no'),
        'room_name': field(row, 'room_name', 'name'),
        'room_type': field(row, 'room_type', 'type'),
        'capacity': field(row, 'capacity') or None,
    }


def minutes(value):
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if isinstance(value, timedelta):
        return int(value.total_seconds() // 60)
    raw = str(value).strip()
    if re.fullmatch(r'\d+(?:\.\d+)?', raw):
        number = float(raw)
        return round(number * (1440 if 0 < number < 1 else 60))
    for format_string in ('%H:%M', '%H:%M:%S', '%I:%M %p', '%I %p'):
        try:
            return minutes(datetime.strptime(raw, format_string).time())
        except ValueError:
            pass
    raise ValueError(f'Unrecognized class time: {value!s}')


def file_rows(sheet, rooms_by_key, aliases, skipped):
    for row in records(sheet.iter_rows(values_only=True)):
        term = str(field(row, 'term', 'sem_flag', 'semester')).strip()
        if not term:
            skipped['missing term'] += 1
            continue
        day_name = utilization._normalise(field(row, 'day', 'weekday')).rstrip('.')
        day = next((name for name in utilization.DAYS if day_name in {name.upper(), name[:3].upper()}), None)
        if day not in utilization.DEFAULT_DAYS:
            skipped['outside weekdays or missing day'] += 1
            yield term, '', '', 0, 0
            continue
        location = room_record(row)
        location['room_number'] = location['room_number'] or location['room_code']
        location['building_name'] = location['building_name'] or location['building_code']
        room = utilization._resolve_room(location, rooms_by_key, aliases)
        if not room:
            skipped['inactive or unmatched room'] += 1
            yield term, '', '', 0, 0
            continue
        start = field(row, 'hour', 'start_hour', 'start_time', 'from_time', 'fromtime', 'start')
        end = field(row, 'end_time', 'to_time', 'totime', 'end')
        try:
            period = re.split(r'\s*[–—-]\s*', start, maxsplit=1) if isinstance(start, str) else [start]
            start_minutes = minutes(period[0])
            end_minutes = minutes(end or period[1]) if end or len(period) > 1 else start_minutes + 60
            if end_minutes <= start_minutes:
                raise ValueError('End must follow start.')
        except ValueError:
            skipped['invalid time'] += 1
            yield term, '', '', 0, 0
            continue
        yield term, room['key'], day, start_minutes, end_minutes


def database_rows(rooms_by_key, aliases):
    for term in utilization._load_semester_choices():
        yield term, '', '', 0, 0
        for row in utilization._load_timetable(term, rooms_by_key, aliases):
            yield term, row['room_key'], row['weekday'], row['start_minutes'], row['end_minutes']


def aggregate(rooms, rows):
    rooms = sorted(rooms, key=lambda room: room['key'])
    positions = {room['key']: index for index, room in enumerate(rooms)}
    days = {day: index for index, day in enumerate(utilization.DEFAULT_DAYS)}
    terms = {}
    for term, room, day, start, end in rows:
        masks = terms.setdefault(term, {})
        if room not in positions or day not in days or end <= start:
            continue
        mask = 0
        for hour in range(8, 17):
            if start < (hour + 1) * 60 and end > hour * 60:
                mask |= 1 << (days[day] * 9 + hour - 8)
        if mask:
            index = positions[room]
            masks[index] = masks.get(index, 0) | mask
    metadata = [[room[key] for key in ('room_name', 'campus', 'building', 'room_type_label', 'capacity', 'room_code', 'building_key')]
                for room in rooms]
    return {'version': 1, 'rooms': metadata, 'terms': terms}


class Command(BaseCommand):
    help = 'Build the offline room utilization JSON from an Excel timetable and a room CSV, or the existing masters.'

    def add_arguments(self, parser):
        parser.add_argument('--timetable', type=Path, help='Timetable .xlsx file')
        parser.add_argument('--rooms', type=Path, help='Room master CSV file')
        parser.add_argument('--sheet', help='Timetable sheet name (defaults to the first sheet)')
        parser.add_argument('--database', action='store_true', help='Use the application’s existing master data')

    def handle(self, *args, **options):
        timetable, room_master = options['timetable'], options['rooms']
        if options['database'] == bool(timetable or room_master) or bool(timetable) != bool(room_master):
            raise CommandError('Use either --database or both --timetable and --rooms.')
        skipped = Counter()
        try:
            if options['database']:
                rooms, by_key, aliases = utilization._load_room_catalog()
                data = aggregate(rooms, database_rows(by_key, aliases))
            else:
                try:
                    from openpyxl import load_workbook
                except ImportError as exc:
                    raise CommandError('Install openpyxl in the offline import environment to read Excel files.') from exc
                with room_master.open(encoding='utf-8-sig', newline='') as file:
                    active = (
                        room_record(row) for row in records(iter(csv.reader(file)))
                        if str(field(row, 'is_active', 'active_status', 'active', 'status', 'room_status')).strip().lower()
                        in {'1', 'true', 'yes', 'y', 'a', 'active'}
                    )
                    rooms, by_key, aliases = utilization._build_room_catalog(active)
                workbook = load_workbook(timetable, read_only=True, data_only=True)
                try:
                    sheet = workbook[options['sheet']] if options['sheet'] else workbook.worksheets[0]
                    data = aggregate(rooms, file_rows(sheet, by_key, aliases, skipped))
                finally:
                    workbook.close()
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        if not data['rooms'] or not data['terms']:
            raise CommandError('No active rooms or timetable terms were found. Check the source columns.')
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=DATA_PATH.parent, delete=False) as file:
            temp_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, separators=(',', ':'))
        try:
            temp_path.replace(DATA_PATH)
        finally:
            temp_path.unlink(missing_ok=True)
        self.stdout.write(f'Saved {len(data["rooms"]):,} rooms and {len(data["terms"]):,} terms ({DATA_PATH.stat().st_size:,} bytes).')
        for reason, count in skipped.items():
            self.stdout.write(f'Skipped {count:,}: {reason}.')
