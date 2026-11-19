# Live classroom booking implementation

This enhancement extends the existing application. No booking records or master-table records were deleted. The GITAM database and SQLite settings remain in use.

## What changed

- Faculty (existing STAFF or TEACHER role) and Admin can book from hourly timetable slots using a SweetAlert popup with campus/building/room, date, start time, plus/minus duration, calculated end time, subject defaults and purpose.
- New bookings must use whole-hour durations within 08:00-16:00. Availability checks cover the entire time range and return conflicting times. Both room conflicts and a faculty member holding overlapping bookings in different rooms are rejected.
- Pending and HOD-approved requests hold room/time slots until rejected or cancelled. Only Admin-confirmed bookings count as confirmed occupancy. All creation and decision transactions use the existing SQLite write mutex.
- Timetable displays the scoped actual status: amber WAITING FOR HOD RESPONSE, blue APPROVED, red REJECTED, green CONFIRMED/BOOKED and grey CANCELLED. Own submission updates immediately; other-session decisions are checked every 4 seconds and reload the current filtered page when changed. Refresh is deferred while a form or popup is active. Rejection popups show reviewer, date and comments. Unrelated request details remain private; their held slots are unavailable for new requests.
- HOD can reconsider rejected and approved decisions until Admin confirmation. Reversing a rejection requires a reconsideration comment; rejection always requires a reason. Availability is rechecked before reconsideration. Existing history entries remain intact.
- HOD and Admin comments/decisions are visible directly in request tables, as well as in the details/history popup.
- Admin can reject pending or HOD-approved requests, confirm approved requests with room allocation and optional comments, create direct bookings, modify eligible bookings and cancel eligible bookings. Admin direct bookings are visible within the relevant campus to Faculty/HOD/HOI. Normal faculty requests remain scoped to their owner/department/campus.
- HOI is read-only. The timetable inventory is restricted to the assigned campus. No booking/action controls are rendered, and mutation endpoints deny HOI requests.
- Admin-only analytics page and API include 8 cards and 11 chart panels: campus, department, statuses, daily/weekly/monthly trends, frequent confirmed rooms, utilization, faculty activity, HOD decisions and direct-vs-faculty sources. Filters cover campus, department, building, room, dates and status. Date ranges are limited to 366 days. Empty data is shown as empty data, with no sample values.
- Utilization is the union of timetable and confirmed-reservation intervals within Monday-Friday 08:00-16:00, divided by selected active-room working hours. Overlap is counted once. Department filters apply to timetable department and booking requester department. Trends use booking dates. HOD statistics count decision events, including reconsiderations.
- Existing UI preferences are retained: no visible internal request numbers, readable audit snapshots, centered details/action dialogs, View and Clear buttons, initial HOD approval without a reason, SweetAlert approval/rejection and final management confirmations.

## Accounts and login

Employee login URLs now show a password-authenticated login page; GET requests no longer sign in as arbitrary employees.

- Nithin: /ulogin/503823, existing password preserved.
- Yasaswi: /ulogin/503795, existing password preserved.
- Venu: /ulogin/503796, vseela@gitam.edu, VSP / CSE, HOI only. A random temporary password was generated at account creation and supplied privately in the final response; it is not in application source or this archive. Password change is mandatory on first login. New password must satisfy the existing Django password validators.

The forced-password-change middleware blocks access to protected pages and mutation APIs until the temporary password is replaced. Existing users are not forced to change their passwords. Existing SSO routes are preserved.

The status values already stored in the database are retained (pending, hod_approved, hod_rejected, confirmed, admin_rejected, cancelled). Human labels match the requested workflow. The existing admin_direct/teacher_request booking sources are retained. No duplicate tables were created.

## Migrations (already applied locally)

- usermanagement/0005_live_booking_permissions: adds must_change_password, default False. Only the newly created Venu account is flagged True.
- workspace/0028_live_booking_permissions: adds admin_comment, admin_decided_by (nullable foreign key to the custom User), admin_decided_at. Backfills these from the latest existing Admin history entry when present, without changing the old history.

Existing booking, history and locking tables are reused. The backup before these migrations is backups/db-before-live-booking-20261116-111936.sqlite3.

## Changed/new file paths

- GSAMS/settings.py (mandatory first-password middleware)
- usermanagement/models.py
- usermanagement/views.py (compatibility login wrapper)
- usermanagement/urls.py
- usermanagement/password_access.py
- usermanagement/migrations/0005_live_booking_permissions.py
- templates/usermanagement/password_login.html
- templates/usermanagement/password_change.html
- workspace/models.py
- workspace/booking_workflow.py
- workspace/booking_analytics.py
- workspace/class_utilization.py
- workspace/urls.py
- workspace/migrations/0028_live_booking_permissions.py
- workspace/test_booking_workflow.py
- workspace/tests.py
- templates/base.html
- templates/workspace/classroom_requests.html
- templates/workspace/class_utilization.html
- templates/workspace/booking_analytics.html
- static/js/classroom_booking.js
- static/js/booking_live.js

The complete source archive includes prerequisite source/migrations from the earlier implementation, so it contains full replacement files rather than fragments. GSAMS/settings.py is not distributed because it contains existing environment secrets; apply the middleware entry below to the existing settings file:

```python
# Immediately after django.contrib.auth.middleware.AuthenticationMiddleware:
'usermanagement.password_access.RequireInitialPasswordChangeMiddleware',
```

## Exact PowerShell commands

```powershell
Set-Location D:\G-SAMS
.\myvenv\Scripts\python.exe manage.py migrate --database default
.\myvenv\Scripts\python.exe manage.py check
.\myvenv\Scripts\python.exe manage.py makemigrations workspace usermanagement --check --dry-run
.\myvenv\Scripts\python.exe manage.py test workspace usermanagement --verbosity 1
.\myvenv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Stop an existing server before running another on port 8001. The local server has been restarted with this implementation. Hard-refresh (Ctrl+F5) to load updated JavaScript.

## Verification

43 automated tests pass against an isolated migrated SQLite test database. They cover all four roles, approval/rejection/reconsideration/history, campus/department scope, self-approval denial, mandatory trimmed comments, direct booking, cancellation, modification, availability including full-duration overlaps and exact conflicting times, working hours, pending duplicate prevention, adjacent slots, faculty overlap across different rooms, CSRF, account login/forced-password change, analytics page/API access, real analytics totals, timetable workflow visibility versus confirmed occupancy, scoped polling changes, and simultaneous writers producing one reservation.

Additional checks: actual role pages render with local database data; actual analytics API returns 11 chart panels; rendered inline/shared JavaScript passes Node syntax checks; duration control event handling is exercised in a JavaScript harness (08:00->09:00, plus->10:00, minus->09:00, maximum end16:00). Live HTTP checks verify password login, HOD dashboard, timetable, and static assets on port8001.

The live HOD dashboard was visually inspected in the existing Chrome window at 1366x720; the rejection reason and reconsideration action were present. Full popup interaction QA was interrupted by user input in the window. The headless browser module could not load. Rendered-page and JavaScript-harness checks do not replace a complete visual interaction run. The application continues to depend on the existing CDN-loaded SweetAlert2 and GITAM styles.
