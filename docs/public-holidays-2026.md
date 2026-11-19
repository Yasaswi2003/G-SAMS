# Public holidays in the weekly timetable

Implemented with the existing weekly timetable and shared holiday/availability helper.

## Source limitation
The attachment available for this task is the user's pasted request. No PDF was present in the accessible attachment folders. Records use the exact Common Holidays transcription supplied in that request, attributed to GITAM Holiday Circular dated 10-12-2025; they have not been independently extracted or verified against the PDF.

## Records added
| Date | Common holiday |
|---|---|
| 2026-01-15 | Sankranthi |
| 2026-01-26 | Republic Day |
| 2026-03-19 | Ugadi |
| 2026-03-20 | Ramzan (ID-UL-FITR) |
| 2026-04-03 | Good Friday |
| 2026-04-14 | Dr. B R Ambedkar Jayanthi |
| 2026-05-27 | Bakrid (ID-UL-ZUHA) |
| 2026-08-15 | Independence Day |
| 2026-09-14 | Vinayaka Chaturthi |
| 2026-10-02 | Mahatma Gandhi Jayanthi |
| 2026-10-20 | Vijayadasami |
| 2026-11-08 | Deepavali |
| 2026-12-25 | Christmas |

One shared record per date applies to every campus. No optional or campus-specific holidays or Christmas Eve are imported. Historical records remain available through weekly navigation.

## Files modified or added
- workspace/models.py: PublicHoliday model, unique date, name, year, common type and source.
- workspace/migrations/0030_public_holiday.py: schema migration.
- workspace/migrations/0031_common_holidays_2026.py: idempotent date-based import of all 13 common dates. Reverse migration deliberately retains imported data.
- workspace/holidays.py: reads common records from the database; short two-second cache; retains the existing helper interfaces used by timetable and booking validation.
- templates/workspace/class_utilization.html: PUBLIC HOLIDAY badge, uppercase holiday name, full date and icon, Public Holiday legend entry.
- static/user/css/classroom_weekly.css: full-column rose background, red borders and badge.
- workspace/test_booking_workflow.py: database records, three campuses, historical dates, previous week, Christmas Eve exclusion, new/revision rejection tests.
- docs/public-holidays-2026.md: this report.

Both migrations have been applied to the local application database. Future annual circulars can be imported as PublicHoliday rows without modifying templates or JavaScript.

## Availability
Existing shared closures_on validation now reads the database records. This covers new requests, availability checks, revision selection and final resubmission. Holiday columns contain no available-slot buttons. Existing timetable and booking rows are retained and can still be inspected. Existing request history is never deleted.

## Preview
Open /workspace/class_utilization?date=2026-12-25 and select a campus/building/room. Friday must display CHRISTMAS, PUBLIC HOLIDAY, and 25 December 2026 on a pink column. Christmas Eve remains a working day. The week of 14 December has no Christmas marker.

Browser screenshot capture was attempted, but the browser access host was unavailable. No screenshot or visual verification is claimed.
