# Official holiday calendar

The requested `holidays-2026.pdf` was not present in the supplied attachments or
workspace during implementation. **No official holiday dates have been imported.**
Do not substitute dates from websites or assumptions.

The reusable calendar is `workspace/data/holiday_calendar.json`. After inspecting
the official circular, add a year entry with its source reference and records:

```json
{
  "schema_version": 1,
  "years": {
    "YEAR": {
      "source": "Official circular filename and reference",
      "holidays": [
        {
          "name": "Exact name from the circular",
          "date": "YYYY-MM-DD",
          "category": "common",
          "campuses": [],
          "description": "Any relevant circular footnote"
        }
      ]
    }
  }
}
```

This is a schema example, not an importable holiday record. Categories:

- `common`: all campuses; campuses must be empty.
- `campus`: explicit `VSP`, `HYD`, or `BLR` campus list.
- `optional`: information only; an empty list means applicable to all campuses.
  These never block rooms and do not imply individual approval.

Keep separate category/campus records when the circular lists the same date in
multiple places. Exact duplicates are deduplicated by date, name, category and
campus scope. `workspace.holidays.validate_calendar` rejects invalid dates,
years, categories and unspecified campus scopes. The loader refreshes when the
file changes (within two seconds); no database model or migration is required.
