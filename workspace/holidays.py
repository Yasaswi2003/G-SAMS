"""Verified, year-scoped circular data. Optional holidays never close rooms."""
import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from time import monotonic

CALENDAR_PATH = Path(__file__).with_name('data') / 'holiday_calendar.json'
CATEGORIES = {'common', 'campus', 'optional'}
CAMPUS_ALIASES = {'VSP':'VSP', 'VISAKHAPATNAM':'VSP', 'HYD':'HYD', 'HYDERABAD':'HYD',
                  'BLR':'BLR', 'BENGALURU':'BLR', 'BANGALORE':'BLR'}


def campus_code(value):
    value = str(value or '').strip().upper()
    return CAMPUS_ALIASES.get(value, value)


def validate_calendar(data):
    """Validate before using circular records; deduplicate only identical scopes."""
    result = {}
    for year, calendar in data.get('years', {}).items():
        year = int(year)
        records, seen = [], set()
        if calendar.get('holidays') and not calendar.get('source'):
            raise ValueError('Holiday records require an official source reference.')
        for record in calendar.get('holidays', []):
            day = date.fromisoformat(record['date'])
            category = record['category']
            campuses = tuple(sorted({campus_code(value) for value in record.get('campuses', [])}))
            name = record['name'].strip()
            if day.year != year or category not in CATEGORIES or not name:
                raise ValueError('Holiday year, category or name is invalid.')
            if category == 'campus' and (not campuses or not set(campuses) <= {'VSP','HYD','BLR'}):
                raise ValueError('Campus holidays require an explicit supported campus.')
            if category == 'common' and campuses:
                raise ValueError('Common holidays apply to every campus; leave campuses empty.')
            identity = (day, name, category, campuses)
            if identity in seen:
                continue
            seen.add(identity)
            records.append({'date': day, 'name': name, 'category': category,
                            'campuses': campuses, 'year': year,
                            'description': record.get('description', ''),
                            'source': calendar.get('source', '')})
        result[year] = {'source': calendar.get('source'), 'holidays': records}
    return result


@lru_cache(maxsize=4)
def _load(path, modified):
    with open(path, encoding='utf-8') as source:
        return validate_calendar(json.load(source))


@lru_cache(maxsize=4)
def _snapshot(path, refresh_bucket):
    source = Path(path)
    if not source.exists():
        return {}
    return _load(str(source), source.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _database_calendar(refresh_bucket):
    from .models import PublicHoliday
    result = {}
    for holiday in PublicHoliday.objects.filter(holiday_type='common').order_by('date'):
        calendar = result.setdefault(holiday.date.year, {'source':holiday.source, 'holidays':[]})
        calendar['holidays'].append({'date':holiday.date,'name':holiday.name,'category':'common',
                                    'campuses':(), 'year':holiday.date.year,'description':'','source':holiday.source})
    return result


def calendar_data():
    # Only common public holidays are imported. Refresh promptly for calendar updates.
    return _database_calendar(int(monotonic() // 2))


def year_available(year):
    return bool(calendar_data().get(year, {}).get('source'))


def holidays_on(day, campus=''):
    campus = campus_code(campus)
    return [record for record in calendar_data().get(day.year, {}).get('holidays', [])
            if record['date'] == day and (not record['campuses'] or campus in record['campuses'])]


def closures_on(day, campus):
    return [record for record in holidays_on(day, campus) if record['category'] != 'optional']


def day_annotations(day, campuses):
    """For all-campus views, a local closure must not close every other campus."""
    campuses = sorted({campus_code(value) for value in campuses if value})
    records = []
    seen = set()
    for campus in campuses or ['']:
        for record in holidays_on(day, campus):
            key = (record['name'], record['category'], record['campuses'])
            if key not in seen:
                seen.add(key)
                records.append({**record, 'scope_label': ', '.join(record['campuses']) or 'All campuses'})
    return {'holidays': records,
            'is_holiday': any(record['category'] == 'common' for record in records) or (bool(campuses) and all(closures_on(day, campus) for campus in campuses)),
            'has_optional': any(record['category'] == 'optional' for record in records)}
