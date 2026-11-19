# Booking details and timetable navigation

The Complete booking history section is removed from the booking details popup. History records and approval/rejection behavior are unchanged. The latest HOD/Admin decision summaries remain visible.

A View Classroom Timetable button is beside Close. It uses the currently selected record; switching popup records replaces the link rather than retaining earlier filters.

## Modified files

- templates/workspace/classroom_requests.html: removes the rendered history loop, renames the table heading to Details, adds the timetable link, and sets it when each View button is clicked.
- workspace/class_utilization.py: validates booking_id against the existing role-scoped visible queryset, resolves the active room-master record, applies the existing campus/building/room parameters, selects the stored date, loads the corresponding academic term and complete daily timetable, and marks overlapping cells for highlighting.
- templates/workspace/class_utilization.html: adds the date control, selected-booking summary and period highlighting. Existing dropdowns are server-populated with their actual selected values. A normal sidebar visit still shows the current weekly timetable.
- workspace/test_booking_workflow.py: adds four focused tests for navigation, full-day rendering/highlighting, switching room/building records, and invalid or unauthorized record IDs.

The complete updated versions of all four files are in artifacts/booking-details-timetable-source.zip. No database migration is required.

## Parameters

Existing report route: /workspace/class_utilization
Existing filters: campus, building, room, q, semester, include_weekends, include_after_hours.
New entry parameter: booking_id. Example /workspace/class_utilization?booking_id=7. This is checked on the backend; it is not trusted to grant access. The room, date and time come from the authorized stored record. Campus/building/room values in the same URL are replaced by that record's validated master values.
New optional normal filter: date=YYYY-MM-DD. When supplied, the complete selected day's schedule is displayed. Without date or booking_id, existing weekly behavior is preserved.

The booked start/end times are not used to truncate the schedule. All hourly rows are retained; cells overlapping the stored duration are outlined. Schedules before, during and after the booking remain visible. Exports and summary cards use the same selected classroom and date. Manual filter submission does not retain booking_id, so the original booking cannot silently override later choices. The Clear button returns to the normal report.

ISO dates and stored local time values are used directly; no browser UTC conversion is involved. Decimal room codes such as 0.5 remain strings. Both canonical room keys and legacy records resolved through existing room aliases are supported.

## Commands

```powershell
Set-Location D:\G-SAMS
.\myvenv\Scripts\python.exe manage.py check
.\myvenv\Scripts\python.exe manage.py test workspace usermanagement --verbosity 0
.\myvenv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Only start the server if another process is not already using port 8001. The running local development server already has these updates.

## Verification

48 backend tests passed, including the four new navigation/permission tests. A selected future date is rendered with all 8 default working-hour rows and a 3-hour booking highlights exactly 3 rows; before/during/after timetable classes are retained. Switching from ICT classroom 101 to GSB classroom 0.5 replaces all room filters. Invalid IDs and unauthorized booking IDs return 404; invalid dates return 400. Direct sidebar visits retain the 5-day weekly report. The booking history database entry count remains unchanged when displaying the popup.

Live HTTP checks returned 200 for the faculty request page and a real booking-specific report. The response no longer includes the Complete booking history section, includes the new timetable link, and renders daily highlighting. The generated popup/report JavaScript passed syntax checks.
