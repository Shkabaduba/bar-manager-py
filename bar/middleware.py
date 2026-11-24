import ipaddress
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

logger = logging.getLogger(__name__)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

DEFAULT_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

DEFAULT_ADMIN_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: blob:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

DEFAULT_PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
)


def get_client_ip(request) -> str:
    """Return client IP, using rightmost trusted proxy hop when enabled."""
    if getattr(settings, "RATE_LIMIT_TRUST_X_FORWARDED_FOR", False):
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        hops = [
            hop.strip()
            for hop in forwarded_for.split(",")
            if hop.strip()
        ]
        if hops:
            proxy_depth = max(
                1,
                int(getattr(settings, "RATE_LIMIT_PROXY_DEPTH", 1)),
            )
            hop_index = max(0, len(hops) - proxy_depth)
            return hops[hop_index]
    return request.META.get("REMOTE_ADDR", "unknown")


def parse_ip_address(raw_ip: str) -> str | None:
    """Validate and normalize IP string for GenericIPAddressField."""
    try:
        return str(ipaddress.ip_address(raw_ip))
    except ValueError:
        return None


def _record_login_blocked(
    client_ip: str,
    path: str,
    attempt_count: int,
) -> None:
    """Persist LOGIN_BLOCKED event to AuditLog without failing the response."""
    from bar.models import AuditLog

    try:
        AuditLog.objects.create(
            action="LOGIN_BLOCKED",
            target_model="Bartender",
            metadata={
                "path": path,
                "attempt_count": attempt_count,
                "raw_ip": client_ip,
            },
            ip_address=parse_ip_address(client_ip),
        )
    except Exception:
        logger.exception("Failed to write LOGIN_BLOCKED audit log entry")


def _increment_counter(cache_key: str, window_seconds: int) -> int:
    """Atomically increment fixed-window counter in cache."""
    if cache.add(cache_key, 1, timeout=window_seconds):
        return 1
    try:
        return cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window_seconds)
        return 1


class SecurityHeadersMiddleware:
    """Attach CSP, Permissions-Policy, Referrer-Policy and nosniff headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/admin/"):
            csp_policy = getattr(
                settings,
                "SECURITY_ADMIN_CSP_POLICY",
                DEFAULT_ADMIN_CSP_POLICY,
            )
        else:
            csp_policy = getattr(
                settings,
                "SECURITY_CSP_POLICY",
                DEFAULT_CSP_POLICY,
            )
        permissions_policy = getattr(
            settings,
            "SECURITY_PERMISSIONS_POLICY",
            DEFAULT_PERMISSIONS_POLICY,
        )
        referrer_policy = (
            getattr(settings, "SECURE_REFERRER_POLICY", None) or "same-origin"
        )
        response.setdefault("Content-Security-Policy", csp_policy)
        response.setdefault("Permissions-Policy", permissions_policy)
        response.setdefault("Referrer-Policy", referrer_policy)
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response


def _resolve_rate_limit_rule(
    request,
    client_ip: str,
) -> tuple[str, str, int, int]:
    login_path = getattr(settings, "LOGIN_URL", "/accounts/login/")
    normalized_path = request.path.rstrip("/")
    login_paths = {login_path.rstrip("/"), "/admin/login"}
    if normalized_path in login_paths:
        return (
            "login",
            f"rl:login:{client_ip}",
            getattr(settings, "RATE_LIMIT_LOGIN_MAX", 10),
            getattr(settings, "RATE_LIMIT_LOGIN_WINDOW", 300),
        )
    if hasattr(request, "user") and request.user.is_authenticated:
        cache_key = f"rl:mutation:user:{request.user.pk}"
    else:
        cache_key = f"rl:mutation:ip:{client_ip}"
    return (
        "mutation",
        cache_key,
        getattr(settings, "RATE_LIMIT_MUTATION_MAX", 60),
        getattr(settings, "RATE_LIMIT_MUTATION_WINDOW", 60),
    )


def _build_rate_limit_response(
    window_seconds: int,
    *,
    is_htmx_request: bool,
) -> HttpResponse:
    response = HttpResponse(
        "Too many requests. Please try again later.",
        status=429,
        content_type="text/plain; charset=utf-8",
    )
    response["Retry-After"] = str(window_seconds)
    if is_htmx_request:
        trigger_payload = {
            "showToast": {
                "level": "error",
                "message": "Too many requests. Please wait and try again.",
            }
        }
        response["HX-Trigger"] = json.dumps(trigger_payload)
    return response


class RateLimitMiddleware:
    """Protect login and mutating endpoints from brute-force and bursts."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            not getattr(settings, "RATE_LIMIT_ENABLED", True)
            or request.method not in MUTATING_METHODS
        ):
            return self.get_response(request)

        client_ip = get_client_ip(request)
        scope, cache_key, limit, window_seconds = _resolve_rate_limit_rule(
            request,
            client_ip,
        )

        attempt_count = _increment_counter(cache_key, window_seconds)
        if attempt_count > limit:
            logger.warning(
                "Rate limit exceeded: scope=%s ip=%s path=%s",
                scope,
                client_ip,
                request.path,
            )
            if scope == "login":
                _record_login_blocked(client_ip, request.path, attempt_count)
            return _build_rate_limit_response(
                window_seconds,
                is_htmx_request=bool(getattr(request, "htmx", False)),
            )

        response = self.get_response(request)
        request_user = getattr(request, "user", None)
        if (
            scope == "login"
            and response.status_code in (301, 302, 303)
            and getattr(request_user, "is_authenticated", False)
        ):
            cache.delete(cache_key)
        return response
