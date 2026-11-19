from django.db import migrations

SOURCE = 'GITAM Holiday Circular, dated 10-12-2025 ? Common Holidays (user-supplied transcription)'
RECORDS = [('2026-01-15', 'Sankranthi'), ('2026-01-26', 'Republic Day'), ('2026-03-19', 'Ugadi'), ('2026-03-20', 'Ramzan (ID-UL-FITR)'), ('2026-04-03', 'Good Friday'), ('2026-04-14', 'Dr. B R Ambedkar Jayanthi'), ('2026-05-27', 'Bakrid (ID-UL-ZUHA)'), ('2026-08-15', 'Independence Day'), ('2026-09-14', 'Vinayaka Chaturthi'), ('2026-10-02', 'Mahatma Gandhi Jayanthi'), ('2026-10-20', 'Vijayadasami'), ('2026-11-08', 'Deepavali'), ('2026-12-25', 'Christmas')]


def import_common_holidays(apps, schema_editor):
    Holiday = apps.get_model('workspace', 'PublicHoliday')
    for day, name in RECORDS:
        Holiday.objects.using(schema_editor.connection.alias).update_or_create(
            date=day, defaults={'name':name, 'year':2026, 'holiday_type':'common', 'source':SOURCE})


class Migration(migrations.Migration):
    dependencies = [('workspace', '0030_public_holiday')]
    operations = [migrations.RunPython(import_common_holidays, migrations.RunPython.noop)]
