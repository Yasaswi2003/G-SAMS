# Shared GITAM typography update

## Findings

The timetable had many independent font-weight:800 declarations on titles, labels, buttons, time labels, subject codes and values. Compact table rules also reduced text to 8-10px. Space Utilization declared DM Sans and JetBrains Mono, analytics SVG text declared Arial, and other pages inherited the external theme font. These competing declarations produced an inconsistent, crowded appearance. The base template referenced static/user/css/styles.css, which does not exist and returned 404. Search Employee itself also contains bold page rules; the reference is its visual clarity rather than copying those declarations.

## Implementation

A single static/user/css/typography.css file now defines reusable font family, size, weight, line-height and letter-spacing variables. Inter is self-hosted with a variable 400-700 font and Segoe UI/Arial/sans-serif fallbacks. Font-display:swap provides readable text while the font loads. Its Latin subset is Unicode-scoped so other scripts can use system fallbacks. The font is distributed with its SIL Open Font License.

The shared file is loaded after page-specific styles in templates/base.html, making its text overrides consistent. Selected important declarations overcome existing page/inline rules. They apply only to text properties. Icon classes, pseudo-elements, images and logos are not assigned the text font. The missing local styles.css reference is removed; the existing GITAM root and Bootstrap styles remain.

Weights: body400, labels/table headings500, page/section headings and buttons600. The stylesheet standardizes modal and SweetAlert text, timetable code/faculty labels, day/date/time labels, status badges, summary values, navigation and analytics SVG labels. It removes text shadow/stroke from headings/buttons without changing colors. Compact layouts retain their original grid, table sizing, responsive rules and components. Text may naturally wrap differently because glyph metrics are now consistent.

The two standalone password pages also load the same shared stylesheet. No backend functions, database models, workflows, charts, filters or application JavaScript were changed.

## Exact modified/new paths

- templates/base.html
- templates/usermanagement/password_login.html
- templates/usermanagement/password_change.html
- static/user/css/typography.css
- static/fonts/inter/Inter-latin.woff2
- static/fonts/inter/OFL.txt

Complete versions of these files and this note are in artifacts/gitam-typography-source.zip. Paths in the archive are relative to D:\G-SAMS. No migrations or package installation are needed.

## Validation

- Django manage.py check passes.
- findstatic resolves the shared CSS and Inter font.
- Live HTTP200 for timetable, booking requests, login page, typography CSS and Inter font.
- Font response has the valid WOFF2 signature; font asset is 48,256bytes.
- The shared CSS contains no color literals and balanced declaration blocks.
- Existing icon styles remain linked.
- Native Chrome was observed, but a refresh/updated visual inspection was interrupted by user input. Live asset checks do not prove a completed visual comparison of every page.

## Commands

```powershell
Set-Location D:\G-SAMS
.\myvenv\Scripts\python.exe manage.py check
.\myvenv\Scripts\python.exe manage.py findstatic user/css/typography.css fonts/inter/Inter-latin.woff2 --verbosity 0
.\myvenv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

The existing local server is already running. Refresh Chrome with Ctrl+F5 to load the updated styles. For deployment, include the new CSS/font/license files when collecting static assets.
