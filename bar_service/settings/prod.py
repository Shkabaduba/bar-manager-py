import dj_database_url
from bar_service.settings.base import *  # noqa: F403, F401
import os

SECRET_KEY = os.environ["SECRET_KEY"]

DEBUG = False

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")  # noqa: F405

DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get("DATABASE_URL"),  # noqa: F405
        conn_max_age=500,
        ssl_require=True,
    )
}
