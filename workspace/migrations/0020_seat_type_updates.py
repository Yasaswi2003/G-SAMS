from django.db import migrations


NEW_SEAT_TYPES = [
    {'name': "Director's Cabin", 'icon': 'bx bx-crown', 'color': '#7C3AED'},
    {'name': "HoD's Cabin", 'icon': 'bx bx-medal', 'color': '#B45309'},
    {'name': 'Faculty Cubicle', 'icon': 'bx bx-table', 'color': '#059669'},
]


def add_new_and_retire_faculty_cabin(apps, schema_editor):
    SeatType = apps.get_model('workspace', 'SeatType')
    db = schema_editor.connection.alias

    for data in NEW_SEAT_TYPES:
        SeatType.objects.using(db).get_or_create(
            name=data['name'],
            defaults={
                'icon': data['icon'],
                'color': data['color'],
                'is_active': True,
            },
        )

    # Soft-hide "Faculty Cabin" from selection instead of deleting it — the FK
    # from Seat to SeatType cascades, so a hard delete would wipe out every
    # existing Faculty Cabin seat and its allocation history.
    SeatType.objects.using(db).filter(name='Faculty Cabin').update(is_active=False)


def reverse(apps, schema_editor):
    SeatType = apps.get_model('workspace', 'SeatType')
    db = schema_editor.connection.alias

    SeatType.objects.using(db).filter(name='Faculty Cabin').update(is_active=True)
    SeatType.objects.using(db).filter(
        name__in=[d['name'] for d in NEW_SEAT_TYPES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0019_rename_current_seat_number_seat_seat_number_and_more'),
    ]

    operations = [
        migrations.RunPython(add_new_and_retire_faculty_cabin, reverse),
    ]
