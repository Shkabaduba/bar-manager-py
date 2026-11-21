import os
import sys

from bar_service.settings.base import *  # noqa: F403


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

STORAGES = {
    **STORAGES,  # noqa: F405
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}

TESTING = "test" in sys.argv

if DEBUG and not TESTING:
    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]  # noqa: F405
    gzip_middleware_index = (
        MIDDLEWARE.index(  # noqa: F405
            "django.middleware.gzip.GZipMiddleware"
        )
        + 1
    )
    MIDDLEWARE = [
        *MIDDLEWARE[:gzip_middleware_index],  # noqa: F405
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE[gzip_middleware_index:],  # noqa: F405
    ]
    INTERNAL_IPS = ["127.0.0.1"]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
