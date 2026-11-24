from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
import polib


class Command(BaseCommand):
    help = (  # noqa: VNE003
        "Compile .po translation files to binary .mo files via polib."
    )

    def handle(self, *args, **options):
        compiled_count = 0
        for locale_dir in getattr(settings, "LOCALE_PATHS", []):
            locale_path = Path(locale_dir)
            if not locale_path.exists():
                continue
            for po_path in sorted(locale_path.rglob("*.po")):
                mo_path = po_path.with_suffix(".mo")
                po_file = polib.pofile(str(po_path))
                po_file.save_as_mofile(str(mo_path))
                compiled_count += 1

        if compiled_count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Compiled {compiled_count} locale file(s)."
                )
            )
        else:
            self.stdout.write("No .po files found to compile.")
