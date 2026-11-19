# Classroom Utilization improvements

## Implemented

- Assigned HOD names come from active users' unblocked HOD assignments matching
  the booking's campus and department. Multiple assignments are listed rather
  than choosing an arbitrary person. Actual reviewers remain separate.
- Approval Timeline starts collapsed, with an accessible toggle, rotating arrow,
  smooth expansion and reduced-motion support. History is retained unchanged.
- Removed Search Timetable, the synchronization notice, and Booking Dashboard
  from the utilization header. Academic semester, campus, building, room, date
  and schedule-period filters remain available.
- Live Schedule uses a small red CSS dot; its refresh behavior is unchanged.
- Fresh timetable visits show the current Monday-Friday week. Previous, Current
  and Next Week links retain academic/campus/building/room/schedule filters and
  remove stale selected-booking focus. The displayed week is explicit.
- Existing Total Classrooms, Avg Utilization, Peak Hour and Idle Rooms metrics
  retain database-derived values and use the Booking Analytics gradient palette,
  readable values, icons, descriptions and responsive layout. No speculative
  metric click actions or fake values were added.
- Reusable holiday lookup supports common, campus-specific and optional dates.
  Common/campus closures are highlighted in rose and cannot be selected as free
  slots or booked through Django. Optional dates are informational only.
  All-campus views do not close working campuses for another campus's holiday.
- The existing shared occupancy calculation excludes verified closed room-days
  from capacity, while retaining its interval-union logic. The heatmap and
  building utilization charts remain on Analytics, not the timetable page.

## Holiday source blocker

`holidays-2026.pdf` was not present in the accessible attachments or workspace.
**Official records imported: 0.** No dates were assumed or obtained elsewhere.
The production JSON calendar deliberately contains no year records. Timetable
pages show a clear notice when the official calendar is not loaded.

Attach the official PDF to finish extracting and verifying every common,
campus-specific and optional holiday. Import instructions and the schema are in
`docs/holiday-calendar.md`. Dates in automated tests are synthetic fixtures,
not official records and are never written to the production calendar.

## Models and migrations

No database models, tables, fields or migrations were added. Holiday records use
year-scoped, source-referenced JSON with validation and exact-duplicate removal.

## Modified or added files

1. `workspace/booking_workflow.py`
2. `workspace/class_utilization.py`
3. `workspace/booking_analytics.py`
4. `workspace/utilization_summary.py`
5. `workspace/holidays.py` (new)
6. `workspace/data/holiday_calendar.json` (new, intentionally empty)
7. `templates/workspace/classroom_requests.html`
8. `templates/workspace/class_utilization.html`
9. `static/js/booking_management.js`
10. `static/user/css/booking_management.css`
11. `static/user/css/classroom_weekly.css` (new)
12. `workspace/test_booking_workflow.py`
13. `workspace/tests.py`
14. `docs/holiday-calendar.md` (new)
15. `docs/classroom-utilization-improvements.md` (this report)

## Verification

`myvenv/Scripts/python.exe manage.py test workspace --noinput`: 94 tests passed.
Coverage includes HOD assignment versus reviewer identity, week navigation and
filter preservation, calendar scope, optional dates, capacity and overlap rules,
role permissions, resubmission/history and simultaneous booking/review actions.

The management, timetable and Analytics pages returned HTTP 200 using existing
authorized accounts. Inline JavaScript compilation and timeline toggle/accessibility
checks passed. Actual browser visual review was not performed in this pass.

## Manual review

1. Open Classroom Utilization without a date; verify the present working week.
2. Select campus/building/room/semester, then navigate previous/next/current week.
3. Verify the four metric values change with the selected scope, and review the
   grid on desktop and mobile.
4. Open a booking's View modal; compare the assigned HOD with the actual reviewer
   and expand/collapse the timeline.
5. After the PDF is imported, review common and campus-specific dates across all
   campuses. Confirm optional dates remain bookable and informational.
