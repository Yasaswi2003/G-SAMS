# Faculty-owned classroom booking workflow

Implemented on the existing SQLite booking, history and role system. This requirement supersedes the previous direct Admin modification and pending-request confirmation behavior.

## Exact permissions

| Active role | Allowed booking actions |
| --- | --- |
| Faculty (STAFF / TEACHER) | View within existing scope; edit/withdraw only own eligible teacher_request records; submit amendment/cancellation proposals for own confirmed records |
| HOD | Department/campus view; approve/reject eligible unconfirmed faculty requests; request changes; existing reconsideration rules |
| Admin | View all; confirm only after HOD approval; reject; request changes; review faculty amendment/cancellation proposals; existing direct-booking creation |
| HOI | Scoped view, details and history only |

HOD, Admin and HOI cannot call Edit/Withdraw APIs. The former modify action is denied, not merely hidden. Admin confirm ignores posted replacement room/date/time/purpose values and rechecks the stored faculty-selected reservation. Initial approval/confirmation requires no comment; rejection, withdrawal, Request Changes, amendment/cancellation requests and rejection of a proposal require trimmed nonempty comments. Reconsidering a HOD rejection still requires a comment.

## Faculty editing and withdrawal

Eligible states: Pending HOD Approval, Changes Requested, Approved by HOD, Rejected by HOD, Rejected by Admin. The faculty must own the record and it must be a teacher request. The reused SweetAlert booking form prepopulates room, date, time, duration, subject defaults and purpose; plus/minus duration recomputes the end time. Subject identity is not editable in this form.

Every edit checks active ROOM_MASTER validity, existing TIME_TABLE_MASTER allocations, all pending/HOD-approved/confirmed room reservations and other active reservations held by the same faculty. The existing SQLite write mutex is acquired before these reads. New/updated time ranges remain whole-hour durations within 08:00-16:00. Pending edits stay pending; all other eligible edits resubmit to Pending HOD Approval. Current review metadata is reset, and previous approval/rejection comments remain in chronological history. Before/after snapshots are recorded. HOD and Admin receive in-app notifications.

Withdrawal sets Withdrawn by Faculty and records the reason, actor and timestamp. It never deletes the record. Withdrawn records remain viewable but cannot be edited or reapproved. They are excluded from the active timetable display and no longer hold the room. Master classes and other reservations continue to block availability. A confirmed booking cannot be edited or withdrawn directly.

## Request Changes and resubmission

HOD/Admin can request changes to eligible unconfirmed faculty requests with mandatory comments. The status becomes Changes Requested and the owner can edit/resubmit or withdraw. Changes Requested releases the pending reservation hold; it does not represent a confirmed allocation. Resubmission validates availability again, sets Pending HOD Approval and requires a fresh HOD review before final Admin confirmation. Prior decisions are not overwritten in history.

## Confirmed amendment/cancellation proposals

Faculty submit a proposal rather than modifying the confirmed record. One pending change request is allowed per booking. Amendment proposals store canonical proposed room/date/time/purpose values; cancellation proposals store the reason. Original values and a revision timestamp are retained. The confirmed booking stays active while either proposal awaits Admin review. The proposed new slot is not reserved at submission.

Admin can accept/reject the submitted proposal only. Acceptance of an amendment rechecks the stored proposal and room availability, verifies that the original record has not changed, and applies the approved values atomically. Acceptance of a cancellation sets the original booking to Cancelled. Rejection leaves its room/date/time/status unchanged and records the Admin decision/comment. Stale revisions and conflicting proposals are blocked. Every request/decision is appended to history, with before/after details where applicable.

The popup contains an expandable Booking history section (restored by this latest requirement), readable snapshots, proposal details and the existing View Classroom Timetable link. HOI also has an explicit History button. Timetable display and polling reuse the existing implementation; no duplicate report was created.

## Notifications

Inspection found no existing notification model, routes or interface in this project. A small in-app layer was added, referencing existing history entries rather than creating a second booking/audit system. The header bell opens the inbox and refreshes its unread count every 15 seconds. It shows action, booking ID, actor, local timestamp, comments and a booking-details link. Opening a notification marks only that recipient's notification as read.

Recipients follow the requested routing: submission -> HOD; edit/withdraw/resubmission -> HOD and Admin; HOD changes/rejection -> faculty; HOD approval -> faculty and Admin; Admin changes -> faculty and HOD; Admin confirmation/rejection and proposal decisions -> faculty, HOD and HOI; amendment/cancellation requests -> Admin. Unblocked assigned roles and active users are considered, HOD recipients match requester department/campus, HOI recipients match requester campus, duplicates are removed, and actors are not notified about their own action. The inbox additionally enforces the recipient's current role visibility.

Notifications are stored in the same transaction as booking and history updates; a storage failure rolls the mutation back. No email, SMS or external messaging service is used. Existing historical events are not retroactively sent as new notifications.

## Database migration

workspace/migrations/0029_faculty_owned_booking_changes.py (already applied locally):

- Adds withdrawal_reason, withdrawn_at, withdrawn_by to the existing booking table.
- Adds Changes Requested and Withdrawn by Faculty choices; existing status values and records are retained.
- Creates workspace_classroom_booking_change_request: booking/requester/reviewer foreign keys, kind, proposed/original JSON values, revision, reason, status and timestamps. A conditional unique constraint permits only one pending proposal per booking.
- Creates workspace_classroom_booking_notification: recipient/history foreign keys, created/read timestamps and a uniqueness constraint for recipient+history.

The existing history table stores the new actions. Neither ROOM_MASTER nor TIME_TABLE_MASTER is modified. SQLite configuration and existing user assignments are unchanged. A pre-migration backup was saved at backups/db-before-faculty-owned-workflow-20261116-160005.sqlite3.

## Complete updated file paths

- workspace/models.py
- workspace/booking_workflow.py
- workspace/booking_notifications.py
- workspace/booking_presentation.py
- workspace/class_utilization.py
- workspace/urls.py
- workspace/migrations/0029_faculty_owned_booking_changes.py
- workspace/test_booking_workflow.py
- workspace/tests.py
- templates/base.html
- templates/workspace/classroom_requests.html
- templates/workspace/class_utilization.html
- static/js/classroom_booking.js
- static/js/booking_notifications.js
- static/js/booking_analytics.js
- static/user/css/booking_notifications.css

Complete replacement source files and this document are included in artifacts/faculty-owned-booking-source.zip. Existing styles/fonts and previous migrations remain prerequisites in the existing project. No account credentials or database files are in the archive.

## Exact PowerShell commands

```powershell
Set-Location D:\G-SAMS
.\myvenv\Scripts\python.exe manage.py migrate --database default
.\myvenv\Scripts\python.exe manage.py check
.\myvenv\Scripts\python.exe manage.py makemigrations workspace --check --dry-run
.\myvenv\Scripts\python.exe manage.py test workspace usermanagement --verbosity 0
.\myvenv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Port8001 is already running the updated code. Do not start a second server on the same port. Refresh with Ctrl+F5 to update the shared JavaScript.

## Verification

65 automated tests pass on an isolated migrated SQLite test database. Coverage includes per-role and own-record permissions; rejection and changes/resubmission; HOD reapproval requirements; mandatory reasons; room/master/overlap validation; withdrawal slot release and terminal state; confirmed edit/withdraw denial; amendment acceptance/conflict/stale revision behavior; cancellation review; original reservation preservation; notification recipient/privacy/read rules; CSRF; rollback when notifications fail; current timetable/report behavior; Admin analytics restrictions; and concurrent overlapping bookings producing only one confirmed reservation.

All four role pages render. Live HTTP200 checks pass for the faculty request page, notifications API and notification assets. Rendered page and shared JavaScript pass syntax checks. A JavaScript popup harness verifies prepopulation, 3-hour end-time calculation and distinct Edit/Amendment submission actions. The CSRF field is rendered before action-handler initialization. No real booking approvals, edits, withdrawals or test notifications were created as part of verification. Full visual interaction testing in Chrome was not performed during this change.
