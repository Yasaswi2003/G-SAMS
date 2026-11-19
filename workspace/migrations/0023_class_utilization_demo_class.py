from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0022_classroom_booking"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClassUtilizationDemoClass",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("campus", models.CharField(max_length=100)),
                ("building", models.CharField(max_length=150)),
                ("room_code", models.CharField(max_length=50)),
                ("room_name", models.CharField(max_length=150)),
                ("room_type", models.CharField(choices=[("classroom", "Classroom"), ("lab", "Laboratory"), ("seminar", "Seminar hall")], max_length=20)),
                ("weekday", models.CharField(choices=[("Monday", "Monday"), ("Tuesday", "Tuesday"), ("Wednesday", "Wednesday"), ("Thursday", "Thursday"), ("Friday", "Friday"), ("Saturday", "Saturday"), ("Sunday", "Sunday")], max_length=12)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("course_code", models.CharField(max_length=50)),
                ("course_name", models.CharField(max_length=200)),
                ("instructor_name", models.CharField(max_length=150)),
                ("instructor_id", models.CharField(blank=True, max_length=50)),
                ("instructor_email", models.EmailField(blank=True, max_length=254)),
                ("section", models.CharField(blank=True, max_length=50)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "workspace_class_utilization_demo_class",
                "ordering": ("weekday", "start_time", "room_name"),
                "indexes": [models.Index(fields=["campus", "building", "room_code", "weekday", "is_active"], name="cu_demo_room_day_active")],
            },
        ),
    ]
