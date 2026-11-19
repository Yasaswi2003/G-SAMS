# Progressive classroom selection

Classroom Utilization now follows Campus -> Building -> Floor -> Classroom cards -> existing weekly timetable. No timetable is displayed on initial entry or before choosing a classroom. Campus options and scoped building/floor/card data come from the existing active room master.

## Data and status
- Exposed the existing unmanaged ROOM_MASTER.FLOOR_CODE column as RoomMaster.floor_code. No physical schema, duplicate room model, or migration is needed.
- Floor values are actual database codes. Missing values appear explicitly as Floor not recorded; floors are never guessed from room numbers.
- Cards show room name/code, building, floor, capacity and availability right now, with timestamp. Pending reservations are yellow, current scheduled/confirmed occupancy rose, available green, and maintenance grey. All cards can open the timetable.
- A room booked at another time stays available now. The weekly timetable and final booking validation remain authoritative for a selected future slot.
- Explicit maintenance flags prevent submission in the backend. Existing same-room conflicts, faculty overlap rules, holidays, ownership and review permissions remain enforced.

## Navigation
Changing campus clears building, floor and classroom. Changing building clears floor and classroom. Changing floor clears classroom. Clicking a card carries those filters into the existing timetable. Back to Classrooms clears only room and preserves campus/building/floor. Weekly navigation preserves every selected location field.

Existing booking-report and revision deep links resolve the room's campus/building/floor from the trusted room catalog. A wrong room/floor combination cannot open another floor's timetable. Revision tokens and original request IDs remain unchanged. Selecting an available replacement uses the existing Use this slot / Back to Your Form popup. No reservation is created before final resubmission. Normal browsing has no special revision return action.

Booking forms receive the selected room, date, start time and one-hour default duration; floor is derived from the room and shown read-only. The existing duration control can adjust end time within existing rules.

## Modified files
- workspace/models.py
- workspace/class_utilization.py
- workspace/classroom_selection.py (new)
- workspace/booking_workflow.py
- templates/workspace/class_utilization.html
- templates/workspace/classroom_selection.html (new)
- templates/workspace/classroom_requests.html (asset version)
- static/js/classroom_booking.js
- static/user/css/classroom_weekly.css
- workspace/test_booking_workflow.py
- docs/classroom-selection-flow.md (this report)

## Validation
105 workspace tests passed. Added progressive selection, campus/building/floor isolation, next-week persistence, Back to Classrooms, current occupancy/pending/withdrawal status and maintenance validation tests. Existing revision, race, holiday and permissions tests also pass. Browser visual review is unavailable in this session; the browser access host did not connect during earlier attempts.
