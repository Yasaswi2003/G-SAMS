# Deploying G-SAMS on Vercel

Import the GitHub repository in Vercel, choose the Django preset if prompted, and use the repository root. Vercel loads the Django application and collects static assets using `STATIC_ROOT`.

Set the following Vercel environment variables for the deployment environment.

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URL for bookings, users, and other application data |
| `GSAMS_GITAM_DATABASE_URL` | PostgreSQL connection URL for the GITAM room, timetable, employee, and guest staff master tables |
| `GSAMS_SECRET_KEY` | A stable Django secret key |
| `GSAMS_ENCRYPT_KEY` | A stable Fernet key. Use the original key when migrating data encrypted with it. |
| `GSAMS_ALLOWED_HOSTS` | Optional comma-separated custom hostnames without a scheme |

Run `python manage.py migrate` against the deployment application database before serving traffic. The GITAM master tables are unmanaged and must be provisioned separately. Use approved master data or synthetic data for the target environment. The local SQLite files are excluded from Git.

After the deployment succeeds, its production URL appears on the Vercel project dashboard.
