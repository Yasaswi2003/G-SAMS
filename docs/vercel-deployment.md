# Deploying G-SAMS on Vercel

Import the GitHub repository in Vercel, choose the Django preset if prompted, and use the repository root. Vercel loads the Django application and collects static assets using `STATIC_ROOT`.

Set the following Vercel environment variables for the deployment environment.

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection URL for bookings, users, and other application data |
| `GSAMS_GITAM_DATABASE_URL` | Optional separate PostgreSQL connection URL for the GITAM master tables. Defaults to `DATABASE_URL`. |
| `GSAMS_SECRET_KEY` | A stable Django secret key |
| `GSAMS_ENCRYPT_KEY` | A stable Fernet key. Use the original key when migrating data encrypted with it. |
| `GSAMS_ALLOWED_HOSTS` | Optional comma-separated custom hostnames without a scheme |

Production builds create the `gsams_app` PostgreSQL schema if needed and apply Django migrations there, using `DATABASE_URL_UNPOOLED` when available. Django reads the unmanaged GITAM master tables through the separate GITAM connection, which keeps its default database search path. Import approved user and application records into `gsams_app` and provision the master tables separately. The local SQLite files are excluded from Git.

After the deployment succeeds, its production URL appears on the Vercel project dashboard.
