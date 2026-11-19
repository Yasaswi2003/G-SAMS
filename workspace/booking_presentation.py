"""Human-readable presentation of stored audit snapshots; storage stays intact."""
import json
from datetime import date


def history_details(comments):
    notes, snapshots = [], []
    labels = {'campus': 'Campus', 'building': 'Building', 'room': 'Classroom', 'date': 'Booking date', 'start': 'Start time', 'end': 'End time', 'purpose': 'Purpose'}
    sections = {'booking': 'Booking details', 'before': 'Before change', 'after': 'After change', 'proposal': 'Proposed changes'}
    for line in (comments or '').splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            notes.append(line)
            continue
        if not isinstance(value, dict) or not value or not set(value).issubset(sections) or not all(isinstance(item, dict) for item in value.values()):
            notes.append(line)
            continue
        for key, snapshot in value.items():
            snapshot = {**snapshot, **{target:snapshot[source] for source,target in [('room_key','room'),('building_name','building'),('booking_date','date'),('from_time','start'),('to_time','end')] if source in snapshot}}
            rows = []
            for field, label in labels.items():
                item = str(snapshot.get(field) or '')
                if not item:
                    continue
                if field == 'room':
                    item = item.rsplit('|', 1)[-1]
                elif field == 'date':
                    try:
                        item = date.fromisoformat(item).strftime('%d %b %Y')
                    except ValueError:
                        pass
                elif field in ('start', 'end'):
                    item = item[:5]
                rows.append({'label': label, 'value': item})
            if rows:
                snapshots.append({'title': sections[key], 'rows': rows})
    return {'comments': '\n'.join(notes).strip(), 'snapshots': snapshots}
