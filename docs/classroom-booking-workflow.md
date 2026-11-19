# Classroom booking workflow

Implemented in the existing Django application. Open `/workspace/classroom_requests` after logging in. The sidebar includes Classroom Requests; timetable BOOK buttons preselect room/date/time on this page. Teacher, HOD and HOI home dashboards open their scoped booking dashboard. Admin retains the existing main dashboard and accesses booking management through Classroom Requests.

## Access rules

| Active existing group | Booking access |
| --- | --- |
| STAFF or TEACHER | Teacher: create requests and view own requests/history |
| HOD | Review pending requests from the same department AND requester campus; cannot review own requests |
| HOI | Read-only monitoring within the assigned requester campus |
| ADMIN | All requests; final allocation/confirmation, direct booking, modification and cancellation |

Role selection reuses UserGroups. Only one active, unblocked role is accepted. Missing role or missing HOD/HOI scope fails closed. Teacher requests require the user's campus and dept_code. Account identity is taken from the authenticated user, never posted teacher details. No real users or role assignments were changed. Configure assignments using the existing user administration; this change does not create login accounts. STAFF is the existing ordinary-user group, so it is accepted as the Teacher role without renaming existing groups. Explicit TEACHER groups are also supported.

HOD scope uses User.dept_code + User.campus. HOI uses User.campus because the existing user model has no separate institution assignment relationship. Additional cross-department authority and HOI mutation authority are not granted. Scope is based on the requester's campus, even when the requested classroom is in another campus.

## Workflow and database changes

`pending` (Pending HOD Approval) -> `hod_approved` (Approved by HOD) -> `confirmed` (Confirmed by Admin).
HOD rejection uses `hod_rejected`; Admin rejection uses `admin_rejected`; Admin cancellation uses `cancelled`.

Reuses `workspace_classroom_booking` (SQLite identifiers are case-insensitive). Adds room_key, booking_source, modified_at, confirmed_by and confirmed_at, and expands status choices. Its existing integer primary key is the unique booking request ID. Existing booked_by references the custom user model. Existing reviewed_by/reviewed_at/review_comment record HOD review; Admin decisions and comments are recorded independently in history, so HOD comments are retained.

Adds `workspace_classroom_booking_history`: booking foreign key, actor user foreign key, role, action, old/new status, comments and timestamp. Entries include booking snapshots; modification entries include before/after snapshots. Each activity and its history are committed in the same transaction. Legacy records receive an explicitly marked import entry. Old approved records remain confirmed reservations; old rejected records become HOD-rejected. Original reviewer identity/date/comments are retained where available; imported entries do not invent historical role data.

Adds a singleton `workspace_classroom_booking_lock` mutex. A write to this row is the FIRST operation inside every mutation transaction, before reading availability. SQLite serializes writers, including across worker processes. A contending writer either waits and sees the committed reservation or receives a retryable busy response, with no partial booking/history commit. The concurrency test verifies one reservation from two overlapping Admin submissions. Pending and HOD-approved requests do not reserve rooms; only confirmed bookings occupy the timetable or block another request. A pending request may later fail confirmation if another reservation wins.

ROOM_MASTER and TIME_TABLE_MASTER remain unmanaged/read-only on the existing GITAM SQLite connection. Active room validation and timetable loading reuse the report catalog and timetable functions. Validation checks the academic term for the booking date, timetable weekday/time overlaps and confirmed reservations. Missing academic-term data fails closed. Admin allocation/confirmation and modification recheck the selected room. Adjacent time slots are allowed. End time must be after start time on the same non-past date. Availability checks are advisory; mutation endpoints recheck.

Migration 0027 has already been applied to the local default database. A pre-migration backup is in `backups/db-before-booking-workflow-20261116-092942.sqlite3`. Neither master table nor SQLite configuration was changed. The missing auth migration dependency in usermanagement/migrations/0001_initial.py was repaired so fresh test databases can migrate. The existing runtime Group.priority customization causes unrelated auth migration drift on a global makemigrations dry run; no Django package files were modified. Use the scoped migration check below for this feature.

## Exact PowerShell commands

```powershell
Set-Location D:\G-SAMS
.\myvenv\Scripts\python.exe manage.py migrate --database default
.\myvenv\Scripts\python.exe manage.py check
.\myvenv\Scripts\python.exe manage.py makemigrations workspace --check --dry-run
.\myvenv\Scripts\python.exe manage.py test workspace usermanagement --verbosity 1
.\myvenv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

The migration source is included; generating it again is unnecessary. Stop a currently running server with Ctrl+C before starting another on port 8001. Open http://127.0.0.1:8001/workspace/classroom_requests and hard-refresh the browser after updating templates.

## Endpoints

- GET /workspace/classroom_requests: scoped role dashboard and details/history; campus, building, room, department, teacher, date, status and text filters.
- GET /workspace/classroom_availability: room_key, booking_date, from_time, to_time; Teacher/Admin only.
- POST /workspace/book_classroom: room_key, booking_date, from_time, to_time, purpose; authenticated identity; Admin creates a confirmed direct booking.
- POST /workspace/review_classroom_booking: booking_id, action, comment. HOD: approve/reject. Admin: confirm/reject/cancel/modify. Confirm/modify accept room_key; modify accepts date/times/purpose. Rejection, cancellation and modification require comments. Mutations require CSRF protection.
- GET /workspace/class_utilization: existing report, with only confirmed reservations included in occupancy.

## Verification

31 automated tests pass: role-specific create/read/process controls; cross-department/campus and own-request denial; teacher identity spoof prevention; HOD/Admin mandatory rejection comments; comment visibility; full approval history; Admin direct booking, modification and cancellation; invalid dates/times and unknown rooms; academic-term availability; timetable conflicts at submission and confirmation; adjacent slots; overlapping confirmations; CSRF; STAFF compatibility; dashboard redirects; weekend report behavior; and simultaneous SQLite writers.

Rendered both dashboard and timetable with local data: HTTP 200. Inline JavaScript syntax checked using Node vm.Script. Live visual/browser validation was unavailable because the existing Chrome window was minimized and browser control was disconnected. Test-only records are created in the isolated test database, not the real booking database.

## Complete source files

The accompanying `artifacts/classroom-booking-workflow-source.zip` contains complete replacement source files, not partial snippets. Paths inside the archive are relative to D:\G-SAMS. Keep the backup and existing environment configuration when installing elsewhere.
