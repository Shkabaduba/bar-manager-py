from bar_service.settings.base import *  # noqa: F403
import os


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-+l@xfrq(vsk6nh26du1c1avj(b-hj2h0qy@@ba@a3n5tqy",
)

DEBUG = True

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}
