import csv
from django.core.management.base import BaseCommand, CommandError
from apps.organizations.models import Department, User


EXPECTED_HEADERS = {'email', 'full_name'}

SAMPLE = """email,full_name,department,role
alice@example.com,Alice Smith,Engineering,user
bob@example.com,Bob Jones,Marketing,user
carol@example.com,Carol White,Finance,admin"""


class Command(BaseCommand):
    help = 'Import/update users from a CSV file. Columns: email, full_name, [department], [role]'

    def add_arguments(self, parser):
        parser.add_argument('--file', '-f', type=str, required=True, help='Path to CSV file')
        parser.add_argument('--dry-run', action='store_true',
                            help='Preview without writing')
        parser.add_argument('--sample', action='store_true',
                            help='Print sample CSV format and exit')

    def handle(self, *args, **options):
        if options['sample']:
            self.stdout.write(SAMPLE)
            return

        dry_run = options['dry_run']

        try:
            rows = self._read(options['file'])
        except FileNotFoundError:
            raise CommandError(f'File not found: {options["file"]}')

        created = updated = errors = 0

        for i, row in enumerate(rows, start=2):
            email     = row.get('email', '').strip().lower()
            full_name = row.get('full_name', '').strip()

            if not email or not full_name:
                self.stderr.write(f'  [row {i}] Missing email or full_name - skipped')
                errors += 1
                continue

            dept_name = row.get('department', '').strip()
            role_raw  = row.get('role', 'user').strip().lower()
            role      = role_raw if role_raw in ('admin', 'user') else 'user'

            if dry_run:
                self.stdout.write(
                    f'  [dry-run row {i}] {email} | {full_name} | dept={dept_name or "-"} | role={role}'
                )
                continue

            dept = None
            if dept_name:
                dept, _ = Department.objects.get_or_create(name=dept_name)

            existing = User.objects.filter(email=email).first()

            if existing:
                existing.full_name  = full_name
                existing.department = dept
                existing.is_active  = True
                # Never downgrade a superuser via CSV import
                if not existing.is_superuser:
                    existing.role = role
                existing.save(update_fields=['full_name', 'department', 'role', 'is_active', 'updated_at'])
                updated += 1
                self.stdout.write(f'  [updated] {email}')
            else:
                user = User(email=email, full_name=full_name, department=dept,
                            role=role, is_active=True)
                user.set_unusable_password()
                user.save()
                created += 1
                self.stdout.write(f'  [created] {email}')

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDry run complete - no changes written.'))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nImport complete. Created: {created}  Updated: {updated}  Errors: {errors}'
                )
            )

    @staticmethod
    def _read(path: str) -> list[dict]:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = set(reader.fieldnames or [])
            missing = EXPECTED_HEADERS - headers
            if missing:
                raise CommandError(f'CSV missing required columns: {", ".join(missing)}')
            return list(reader)
