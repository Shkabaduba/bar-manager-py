from pathlib import Path
import re

from django.conf import settings
from django.core.management.base import BaseCommand

CRITICAL_CSS_FILES = (
    "tokens.css",
    "bento.css",
    "components.css",
)


def minify_css(source_text: str) -> str:
    """Strip comments and redundant whitespace while keeping selectors safe."""
    cleaned = re.sub(r"/\*.*?\*/", "", source_text, flags=re.DOTALL)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s*\{\s*", "{", cleaned)
    cleaned = re.sub(r"\s*\}\s*", "}", cleaned)
    cleaned = re.sub(r";\s*", ";", cleaned)
    cleaned = re.sub(r",\s+", ",", cleaned)
    cleaned = re.sub(r":\s+", ":", cleaned)
    return cleaned.replace(";}", "}")


class Command(BaseCommand):
    help = (  # noqa: VNE003
        "Bundle and minify critical and async CSS assets into static/css/."
    )

    def handle(self, *args, **options):
        css_dir = Path(settings.BASE_DIR) / "static" / "css"
        critical_parts = [
            (css_dir / filename).read_text(encoding="utf-8")
            for filename in CRITICAL_CSS_FILES
        ]
        app_bundle = minify_css("\n".join(critical_parts))
        app_path = css_dir / "app.min.css"
        app_path.write_text(app_bundle, encoding="utf-8")

        animations_source = (css_dir / "animations.css").read_text(
            encoding="utf-8"
        )
        animations_bundle = minify_css(animations_source)
        animations_path = css_dir / "animations.min.css"
        animations_path.write_text(animations_bundle, encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Built {app_path.name} ({len(app_bundle)} B) and "
                f"{animations_path.name} ({len(animations_bundle)} B)."
            )
        )
