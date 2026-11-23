# Room utilization

The Room Utilization data endpoint is available to Admins. The former dashboard used
an offline snapshot of room names and occupied timetable slots.

## Refresh from the master files

Use a Python environment with the project dependencies and `openpyxl`. The
Excel file may use `term, campus, building, room, day, hour` as its header row.
An optional end time can be provided as `end_time`. The room CSV may use
`campus, building, room, name, type, capacity, active`. Keep room IDs with
leading zeroes as text. Active values include `1`, `true`, `yes`, `A`,
and `active`.

```powershell
python manage.py build_room_utilization --timetable "path/to/timetable.xlsx" --rooms "path/to/rooms.csv"
```

Add `--sheet "Sheet name"` to read a sheet other than the first one, or run
`python manage.py build_room_utilization --database` to use the application's
existing university master tables.

The command writes `workspace/data/room_utilization.json`. Generate this file
in each environment where the dashboard should be available. The raw files and
generated dataset need not be committed to Git. The dataset is served through
an Admin-only endpoint.

Every active room contributes 45 possible slots per week. A class uses an hour
slot if any part of the class overlaps it, and overlapping classes in the same
room and slot count once. The day filter uses nine possible slots per room.
