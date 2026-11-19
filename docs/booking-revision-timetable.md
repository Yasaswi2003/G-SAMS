# Timetable-based booking revisions

## Navigation

1. HOD or Admin requests changes with a mandatory comment. The original hold is
   released by the existing `changes_requested` availability rule.
2. The owner opens **More -> Respond & Resubmit**. The compact form preserves
   original fields and shows the reviewer comments.
3. The contextual timetable link posts the current form to
   `booking_revision_start`, then navigates to the existing Classroom Utilization
   page with an opaque revision token. Campus, building, room and date are seeded
   from the draft; extended hours are shown for evening selections.
4. Timetable filters and weekly navigation retain the revision token. Selecting
   an available cell opens the existing form in selection-only mode. **Use this
   slot** validates it, saves the temporary selection, and reveals **Back to Your
   Form**. This does not create a booking, hold, or history entry.
5. Back opens the same revision form with the selected slot prefilled and
   highlighted. Purpose and unchanged metadata are preserved.
6. **Save & Resubmit** uses the existing edit/review endpoint and write mutex.
   It validates ownership, revision freshness, holidays, timetable occupancy,
   held/confirmed bookings and faculty overlaps before updating the original ID.
   History records before/after values. The draft is cleared on success, and the
   faculty returns to the Pending Approval tab after the acknowledgement.

Normal timetable visits do not show revision navigation. Existing approved,
rejected and withdrawn request restrictions are unchanged.

## Session and security

- Uses the existing Django session backend (database-backed by default), not
  browser storage or a new booking table.
- Tokens are random and bound to owner ID, request ID and `modified_at` revision.
- Two-hour expiry and a maximum of five drafts per session. Refresh and navigation
  preserve the selection. Reopening Respond & Resubmit recovers the latest valid
  draft for that request.
- HOD, Admin, HOI and other faculty cannot access or alter the draft.
- POST endpoints retain Django CSRF protection. Invalid/stale/expired contexts
  return clear 4xx responses; the original booking is not changed.
- Selecting is advisory. Final resubmission revalidates under the existing mutex;
  another booking can win the slot before submission. The form retains its data
  and offers/uses the timetable link to select again.
- New initial bookings retain the original 08:00-16:00 policy. Returned revisions
  can select 08:00-22:00, supporting the requested 16:00-18:00 example. Duration is
  still 1-8 whole hours. Later review honors an already-resubmitted evening slot.

## Demonstrated scenario

The isolated automated scenario uses Nithin / 503823, VSP, ChB rooms 132 and 135:

| Step | Result |
|---|---|
| Submit ChB 132, 08:00-10:00, purpose `test` | One Pending Approval request |
| Admin: "Please change your 2-hour booking to an evening slot." | Same ID becomes Changes Requested |
| Open timetable and select ChB 135, 16:00-18:00 | Session draft only; original row/history unchanged |
| Refresh and return to form | New slot, original purpose, subject and reviewer comment retained |
| Save & Resubmit | Same ID, ChB 135, Pending Approval; Resubmitted history with before/after rooms |
| HOD approves | Confirmed; a later conflicting Admin decision is rejected |

The test uses the next booking date (18 November 2026 when run on 17 November
2026). No real Nithin account or production booking was modified for the demo.

## Modified files

- `workspace/booking_revisions.py` (new session service and three endpoints)
- `workspace/urls.py`
- `workspace/booking_workflow.py`
- `workspace/class_utilization.py`
- `templates/workspace/classroom_requests.html`
- `templates/workspace/class_utilization.html`
- `static/js/classroom_booking.js`
- `static/user/css/booking_conflict.css`
- `static/user/css/classroom_weekly.css`
- `workspace/test_booking_workflow.py`
- `docs/booking-revision-timetable.md` (this report)

No model or migration was added. Existing URLs and approval endpoints remain.

## Tests

The workspace suite contains 100 tests, covering the full round trip, ownership,
role restrictions, CSRF, expiry, stale revisions, invalid slots, refresh/draft
recovery, final conflict checks, and simultaneous revision/new-booking attempts.

Run:

```powershell
.\myvenv\Scripts\python.exe manage.py test workspace --noinput
```

Browser visual testing remains outstanding; JavaScript syntax and rendered-page
wiring are checked independently of the database workflow tests.
