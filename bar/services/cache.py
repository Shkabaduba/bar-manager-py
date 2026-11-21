from django.core.cache import cache
from django.db import transaction

ANALYTICS_CACHE_VERSION_KEY = "bar:analytics:version"


def get_analytics_cache_version() -> int:
    """Return current analytics cache version, initializing if absent."""
    version = cache.get(ANALYTICS_CACHE_VERSION_KEY)
    if version is None:
        cache.add(ANALYTICS_CACHE_VERSION_KEY, 1, timeout=None)
        version = cache.get(ANALYTICS_CACHE_VERSION_KEY, 1)
    return int(version)


def invalidate_analytics_cache() -> None:
    """Bump analytics cache version so stale dashboard snapshots expire."""
    try:
        cache.incr(ANALYTICS_CACHE_VERSION_KEY)
    except ValueError:
        cache.set(ANALYTICS_CACHE_VERSION_KEY, 2, timeout=None)


def schedule_analytics_cache_invalidation() -> None:
    """Invalidate analytics cache only after the DB transaction commits."""
    transaction.on_commit(invalidate_analytics_cache)
