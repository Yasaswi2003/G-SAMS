"""Initialize the application schema during a Vercel production build."""

import os

import django
from django.core.management import call_command
from django.db import connection


def main():
    if os.getenv('VERCEL') != '1' or os.getenv('VERCEL_ENV') != 'production':
        return
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'GSAMS.settings')
    django.setup()
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA IF NOT EXISTS gsams_app')
    call_command('migrate', interactive=False)


if __name__ == '__main__':
    main()
