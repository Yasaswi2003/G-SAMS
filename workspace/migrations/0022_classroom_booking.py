from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0021_room_room_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassroomBooking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('campus_code', models.CharField(max_length=20)),
                ('building_name', models.CharField(max_length=150)),
                ('room_code', models.CharField(max_length=50)),
                ('semester_flag', models.CharField(max_length=30)),
                ('booking_date', models.DateField()),
                ('from_time', models.TimeField()),
                ('to_time', models.TimeField()),
                ('title', models.CharField(max_length=150)),
                ('purpose', models.TextField()),
                ('details', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
                ('booked_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='classroom_bookings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'workspace_classroom_booking',
                'ordering': ('booking_date', 'from_time'),
            },
        ),
        migrations.AddIndex(
            model_name='classroombooking',
            index=models.Index(fields=['campus_code', 'room_code', 'booking_date', 'is_active'], name='classbook_camp_room_date'),
        ),
    ]
