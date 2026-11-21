from functools import wraps
import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.contrib.auth.views import redirect_to_login
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render

from bar.models import Bartender

OWNER_ROLES = (Bartender.Role.OWNER,)
MANAGER_ROLES = (Bartender.Role.OWNER, Bartender.Role.MANAGER)
ALL_ROLES = (
    Bartender.Role.OWNER,
    Bartender.Role.MANAGER,
    Bartender.Role.BARTENDER,
)

ROLE_GROUP_NAMES = {
    Bartender.Role.OWNER: "Owners",
    Bartender.Role.MANAGER: "Managers",
    Bartender.Role.BARTENDER: "Bartenders",
}

DEFAULT_DENIED_MESSAGE = "You do not have permission to perform this action."


class StaffActionNotAllowedError(Exception):
    """Raised when a staff update or deletion violates safety invariants."""


def user_has_role(user, allowed_roles) -> bool:
    """Return True if user is superuser or has one of allowed_roles."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.role in allowed_roles


def htmx_forbidden_response(
    request,
    message: str = DEFAULT_DENIED_MESSAGE,
) -> HttpResponse:
    """Return HTTP 403 tailored for HTMX toast or full HTML page."""
    if getattr(request, "htmx", False):
        response = HttpResponse(
            message,
            status=403,
            content_type="text/plain; charset=utf-8",
        )
        trigger_payload = {
            "showToast": {"level": "error", "message": message}
        }
        response["HX-Trigger"] = json.dumps(trigger_payload)
        return response
    return render(request, "403.html", {"error_message": message}, status=403)


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict CBV access to authenticated users with matching bar roles."""

    allowed_roles: tuple[str, ...] = ()
    permission_denied_message = DEFAULT_DENIED_MESSAGE

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_has_role(request.user, self.allowed_roles):
            return htmx_forbidden_response(
                request,
                self.permission_denied_message,
            )
        return super().dispatch(request, *args, **kwargs)


def role_required(*allowed_roles, message: str | None = None):
    """Restrict FBV access to authenticated users with matching bar roles."""
    denied_message = message or DEFAULT_DENIED_MESSAGE

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_has_role(request.user, allowed_roles):
                return htmx_forbidden_response(request, denied_message)
            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def sync_bartender_group(bartender: Bartender) -> Group:
    """Ensure bartender belongs only to the Django Group matching its role."""
    group_name = ROLE_GROUP_NAMES.get(bartender.role, "Bartenders")
    target_group, _ = Group.objects.get_or_create(name=group_name)
    other_group_names = [
        name for name in ROLE_GROUP_NAMES.values() if name != group_name
    ]
    bartender.groups.remove(
        *Group.objects.filter(name__in=other_group_names)
    )
    bartender.groups.add(target_group)
    return target_group


def count_active_owners(exclude_pk: int | None = None) -> int:
    """Count active owners or superusers, optionally excluding one user."""
    queryset = Bartender.objects.filter(is_active=True).filter(
        Q(role=Bartender.Role.OWNER) | Q(is_superuser=True)
    )
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.count()


def validate_can_delete_bartender(
    actor: Bartender,
    target: Bartender,
) -> None:
    """Prevent self-deletion and deletion of the last active owner."""
    if actor.pk == target.pk:
        raise StaffActionNotAllowedError("You cannot delete your own account.")
    if target.is_owner and count_active_owners(exclude_pk=target.pk) == 0:
        raise StaffActionNotAllowedError(
            "Cannot delete the last active owner."
        )


def validate_can_change_role(
    actor: Bartender,
    target: Bartender,
    new_role: str,
) -> None:
    """Prevent self-role-change and demoting the last active owner."""
    if actor.pk == target.pk and new_role != target.role:
        raise StaffActionNotAllowedError("You cannot change your own role.")
    if (
        target.is_owner
        and new_role != Bartender.Role.OWNER
        and not target.is_superuser
        and count_active_owners(exclude_pk=target.pk) == 0
    ):
        raise StaffActionNotAllowedError(
            "Cannot demote the last active owner."
        )
