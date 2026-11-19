import json
from datetime import date, time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from .class_utilization import (
    _build_room_catalog,
    get_current_semester,
    _get_active_semester,
    _filters,
    _resolve_room,
    _scheduled_hours_by_day,
    _semester_choices,
    book_classroom,
    class_utilization,
    review_classroom_booking,
    classroom_requests,
)
from .models import ClassroomBooking


class ClassUtilizationMasterDataTests(SimpleTestCase):
    def test_semester_choices_normalize_valid_master_values(self):
        self.assertEqual(
            _semester_choices([
                "2026-2027#odd", " 2025-2026#EVEN ", "remove",
                "2024-07-26 00:00:00", None,
            ]),
            ["2025-2026#EVEN", "2026-2027#ODD"],
        )

    def test_current_semester_auto_updates_based_on_calendar_month(self):
        # July - December is ODD semester
        self.assertEqual(get_current_semester(date(2026, 11, 13)), "2026-2027#ODD")
        self.assertEqual(get_current_semester(date(2026, 7, 1)), "2026-2027#ODD")
        # January - June is EVEN semester of previous start year
        self.assertEqual(get_current_semester(date(2027, 2, 10)), "2026-2027#EVEN")
        self.assertEqual(get_current_semester(date(2027, 6, 30)), "2026-2027#EVEN")

    def test_active_semester_locks_to_current_academic_term(self):
        semesters = ["2025-2026#EVEN", "2026-2027#ODD", "2026-2027#EVEN"]
        self.assertEqual(
            _get_active_semester(semesters, date(2026, 11, 12)),
            "2026-2027#ODD",
        )

    def test_scheduled_hours_default_to_weekdays(self):
        schedules = [
            {"weekday": "Monday", "duration_minutes": 90, "room_master_match": True},
            {"weekday": "Saturday", "duration_minutes": 60, "room_master_match": True},
        ]

        hours_by_day = _scheduled_hours_by_day(
            schedules,
            ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"),
        )

        self.assertEqual(hours_by_day["Monday"], 1.5)
        self.assertNotIn("Saturday", hours_by_day)

    def test_scheduled_hours_include_weekends_when_selected(self):
        schedules = [
            {"weekday": "Monday", "duration_minutes": 60, "room_master_match": True},
            {"weekday": "Saturday", "duration_minutes": 120, "room_master_match": True},
            {"weekday": "Sunday", "duration_minutes": 60, "room_master_match": True},
        ]
        all_days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        hours_by_day = _scheduled_hours_by_day(schedules, all_days)
        self.assertEqual(hours_by_day["Saturday"], 2.0)
        self.assertEqual(hours_by_day["Sunday"], 1.0)
        self.assertEqual(hours_by_day["Monday"], 1.0)

    def test_duplicate_room_master_rows_are_collapsed_and_keep_aliases(self):
        rooms, room_by_key, aliases = _build_room_catalog([
            {
                "campus_code": "VSP", "building_code": "ARB", "building_name": "ArB",
                "room_code": "305", "room_number": None, "room_name": None,
                "capacity": None, "room_category": None, "theory_lab": None, "room_type": None,
            },
            {
                "campus_code": "VSP", "building_code": "ArB", "building_name": "ArB",
                "room_code": "305", "room_number": "ArB-305", "room_name": "Studio",
                "capacity": 40, "room_category": "Class Room", "theory_lab": "Theory",
                "room_type": "Flat",
            },
        ])

        self.assertEqual(len(rooms), 1)
        room = rooms[0]
        self.assertEqual(room["room_name"], "Studio")
        self.assertEqual(room["capacity"], 40)
        self.assertEqual(aliases[("VSP", "ARB-305")], {room["key"]})
        self.assertEqual(room_by_key[room["key"]], room)

    def test_timetable_room_is_matched_by_campus_and_building(self):
        rooms, room_by_key, aliases = _build_room_catalog([
            {
                "campus_code": "VSP", "building_code": "ICT", "building_name": "ICT Block",
                "room_code": "305", "room_number": "ICT-305", "room_name": "ICT 305",
                "capacity": 40, "room_category": "Class Room", "theory_lab": "Theory",
                "room_type": "Flat",
            },
            {
                "campus_code": "VSP", "building_code": "ARB", "building_name": "ArB",
                "room_code": "305", "room_number": "ArB-305", "room_name": "Architecture 305",
                "capacity": 40, "room_category": "Class Room", "theory_lab": "Theory",
                "room_type": "Flat",
            },
        ])

        match = _resolve_room({
            "campus_code": "VSP",
            "room_number": "305",
            "building_name": "ARB",
        }, room_by_key, aliases)

        self.assertIsNotNone(match)
        self.assertEqual(match["building_code"], "ARB")
        self.assertEqual(match["room_name"], "Architecture 305")

    def test_day_filter_is_omitted_and_full_week_schedules_retained(self):
        # Day filter was removed per user requirement
        schedules = [
            {"campus": "VSP", "campus_key": "VSP", "building_key": "VSP|ICT", "room_key": "101", "weekday": "Monday", "subject_code": "CS1"},
            {"campus": "VSP", "campus_key": "VSP", "building_key": "VSP|ICT", "room_key": "101", "weekday": "Friday", "subject_code": "CS2"},
        ]
        filters = _filters(
            RequestFactory().get("/workspace/class_utilization", {"campus": "VSP", "building": "VSP|ICT"}),
            [],
            schedules,
            ["2026-2027#ODD"],
        )
        self.assertEqual(len(filters["classes"]), 2)
        self.assertNotIn("day_choices", filters)


class ClassroomBookingTests(SimpleTestCase):
    room = {
        "key": "VSP|ICT|101",
        "campus": "VSP",
        "building": "ICT Block",
        "building_code": "ICT",
        "room_code": "101",
    }

    def setUp(self):
        self.teacher = SimpleNamespace(
            id=1,
            is_authenticated=True,
            is_active=True,
            username="502971",
            first_name="Kishore",
            last_name="Singh",
            email="kpandey@gitam.edu",
            campus="VSP",
            dept_code="CSE",
        )
        self.booking_date = date.today()
        self.post_data = {
            "semester": "2026-2027#ODD",
            "room_key": self.room["key"],
            "booking_date": self.booking_date.isoformat(),
            "from_time": "12:00",
            "duration_hours": "2",
            "teacher_name": "Kishore Singh",
            "teacher_id": "502971",
            "teacher_email": "kpandey@gitam.edu",
            "subject_code": "CSEN2001",
            "subject_name": "Data Structures",
            "purpose": "Remedial class",
            "details": "Covers trees and graphs",
        }

    def post_booking(self):
        request = RequestFactory().post("/workspace/book_classroom", self.post_data)
        request.user = self.teacher
        return request

    @patch("workspace.class_utilization._load_timetable", return_value=[])
    @patch("workspace.class_utilization._load_room_catalog")
    @patch("workspace.class_utilization._load_semester_choices", return_value=["2026-2027#ODD"])
    @patch("workspace.booking_workflow.role", return_value="HOD")
    def test_timetable_default_shows_monday_to_friday(self, ug_filter, _semesters, room_catalog, _timetable):
        rooms, room_by_key, aliases = _build_room_catalog([{
            "campus_code": "VSP", "building_code": "ICT", "building_name": "ICT Block",
            "room_code": "101", "room_number": "101", "room_name": "ICT 101",
            "capacity": 40, "room_category": "Class Room", "theory_lab": "Theory", "room_type": "Flat",
        }])
        room_catalog.return_value = (rooms, room_by_key, aliases)

        request = RequestFactory().get("/workspace/class_utilization", {"campus": "VSP", "building": "VSP|ICT"})
        request.user = self.teacher

        with patch("workspace.booking_workflow.visible", return_value=Mock(filter=Mock(return_value=Mock(exclude=Mock(return_value=[]))))), \
                patch.object(ClassroomBooking.objects, "filter", return_value=[]), \
                patch.object(ClassroomBooking.objects, "select_related", return_value=Mock(filter=Mock(return_value=Mock(filter=Mock(return_value=Mock(exclude=Mock(return_value=[]))))))), \
                patch("workspace.classroom_maintenance.window_map", return_value={}), \
                patch("workspace.class_utilization.render", return_value=HttpResponse()) as render_page:
            response = class_utilization(request)

        context = render_page.call_args.args[2]
        self.assertEqual(response.status_code, 200)
        # Default view: Monday to Friday (5 visible days)
        self.assertEqual(len(context["visible_days"]), 5)
        self.assertEqual(context["visible_days"], ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"))
        self.assertFalse(context["include_weekends"])

    @patch("workspace.class_utilization._load_timetable", return_value=[])
    @patch("workspace.class_utilization._load_room_catalog")
    @patch("workspace.class_utilization._load_semester_choices", return_value=["2026-2027#ODD"])
    @patch("workspace.booking_workflow.role", return_value="HOD")
    def test_timetable_includes_weekends_when_toggled(self, ug_filter, _semesters, room_catalog, _timetable):
        rooms, room_by_key, aliases = _build_room_catalog([{
            "campus_code": "VSP", "building_code": "ICT", "building_name": "ICT Block",
            "room_code": "101", "room_number": "101", "room_name": "ICT 101",
            "capacity": 40, "room_category": "Class Room", "theory_lab": "Theory", "room_type": "Flat",
        }])
        room_catalog.return_value = (rooms, room_by_key, aliases)

        request = RequestFactory().get("/workspace/class_utilization", {
            "campus": "VSP", "building": "VSP|ICT", "include_weekends": "1"
        })
        request.user = self.teacher

        with patch("workspace.booking_workflow.visible", return_value=Mock(filter=Mock(return_value=Mock(exclude=Mock(return_value=[]))))), \
                patch.object(ClassroomBooking.objects, "filter", return_value=[]), \
                patch.object(ClassroomBooking.objects, "select_related", return_value=Mock(filter=Mock(return_value=Mock(filter=Mock(return_value=Mock(exclude=Mock(return_value=[]))))))), \
                patch("workspace.classroom_maintenance.window_map", return_value={}), \
                patch("workspace.class_utilization.render", return_value=HttpResponse()) as render_page:
            response = class_utilization(request)

        context = render_page.call_args.args[2]
        self.assertEqual(response.status_code, 200)
        # Weekends included: 7 visible days (Mon to Sun)
        self.assertEqual(len(context["visible_days"]), 7)
        self.assertEqual(context["visible_days"][-2:], ("Saturday", "Sunday"))
        self.assertTrue(context["include_weekends"])



class UtilizationSummaryRangeTests(SimpleTestCase):
    def test_weekday_average_uses_actual_dates_and_unions_overlaps(self):
        from .utilization_summary import summarize_utilization
        rooms=[{'key':'r1','campus':'VSP','building':'Main'}]
        events=[{'room_key':'r1','weekday':'Monday','date':'2026-11-02','start_minutes':480,'end_minutes':540},
                {'room_key':'r1','weekday':'Monday','date':'2026-11-02','start_minutes':510,'end_minutes':570}]
        summary=summarize_utilization(rooms,events,('Monday','Tuesday','Wednesday','Thursday','Friday'),8,16,
                                     dates=[date(2026,11,2),date(2026,11,9)])
        self.assertEqual(summary['occupied_minutes'],90)
        self.assertEqual(summary['capacity_minutes'],960)
        self.assertEqual(summary['heatmap'][0]['cells'][0]['value'],50)
        self.assertEqual(summary['heatmap'][0]['cells'][1]['value'],25)
        self.assertEqual(summary['buildings'][0]['value'],9)
        self.assertTrue(all(0<=cell['value']<=100 for row in summary['heatmap'] for cell in row['cells']))

    def test_weekly_summary_retains_original_levels_and_clips_working_hours(self):
        from .utilization_summary import summarize_utilization
        rooms=[{'key':'r1','campus':'VSP','building':'Main'}]
        events=[{'room_key':'r1','weekday':'Monday','start_minutes':420,'end_minutes':540}]
        summary=summarize_utilization(rooms,events,('Monday',),8,16)
        self.assertEqual(summary['occupied_minutes'],60)
        self.assertEqual(summary['heatmap'][0]['cells'][0]['level'],5)
        self.assertEqual(summary['heatmap'][0]['cells'][0]['value'],100)


class HolidayCalendarTests(SimpleTestCase):
    def test_scope_optional_and_duplicate_rules(self):
        from .holidays import validate_calendar,holidays_on,closures_on,day_annotations
        day=date(2026,11,18)
        common={'name':'Fixture common','date':str(day),'category':'common','campuses':[]}
        local={'name':'Fixture local','date':str(day),'category':'campus','campuses':['VSP']}
        optional={'name':'Fixture optional','date':str(day),'category':'optional','campuses':[]}
        calendar=validate_calendar({'years':{'2026':{'source':'Test fixture only','holidays':[common,common,local,optional]}}})
        self.assertEqual(len(calendar[2026]['holidays']),3)
        with patch('workspace.holidays.calendar_data',return_value=calendar):
            self.assertEqual(len(holidays_on(day,'VSP')),3)
            self.assertEqual(len(holidays_on(day,'HYD')),2)
            self.assertEqual(len(closures_on(day,'VSP')),2)
        calendar=validate_calendar({'years':{'2026':{'source':'Test fixture only','holidays':[local,optional]}}})
        with patch('workspace.holidays.calendar_data',return_value=calendar):
            self.assertFalse(day_annotations(day,['VSP','HYD'])['is_holiday'])
            self.assertTrue(day_annotations(day,['VSP'])['is_holiday'])
            self.assertFalse(closures_on(day,'BLR'))

    def test_closures_are_removed_from_capacity_without_changing_other_rooms(self):
        from .utilization_summary import summarize_utilization
        rooms=[{'key':'vsp','campus':'VSP','building':'Main'},{'key':'hyd','campus':'HYD','building':'Main'}]
        events=[{'room_key':key,'weekday':'Monday','start_minutes':480,'end_minutes':540} for key in ('vsp','hyd')]
        result=summarize_utilization(rooms,events,('Monday',),8,16,closures={('vsp','Monday')})
        self.assertEqual(result['occupied_minutes'],60)
        self.assertEqual(result['capacity_minutes'],480)
        self.assertEqual(result['heatmap'][0]['cells'][0]['value'],100)

    def test_invalid_campus_or_year_is_rejected(self):
        from .holidays import validate_calendar
        for record in [dict(name='Fixture',date='2027-01-01',category='common'),
                       dict(name='Fixture',date='2026-01-01',category='campus',campuses=[])]:
            with self.assertRaises(ValueError):
                validate_calendar({'years':{'2026':{'source':'Test fixture only','holidays':[record]}}})
