import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import generic

from bar.services.analytics import get_dashboard_snapshot
from bar.services.cache import invalidate_analytics_cache


def is_htmx(request) -> bool:
    """Return True if request originated from HTMX."""
    return bool(getattr(request, "htmx", False))


def is_htmx_partial(request) -> bool:
    """Return True for partial HTMX requests (excluding hx-boosted nav)."""
    htmx = getattr(request, "htmx", None)
    return bool(htmx) and not bool(getattr(htmx, "boosted", False))


def add_htmx_toast(
    response: HttpResponse,
    *,
    level: str,
    message: str,
    extra_triggers: dict | None = None,
) -> HttpResponse:
    """Attach showToast trigger payload to HX-Trigger response header."""
    existing_raw = response.get("HX-Trigger")
    payload: dict = {}
    if existing_raw:
        try:
            parsed = json.loads(existing_raw)
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            payload = {}

    payload["showToast"] = {"level": level, "message": message}
    if extra_triggers:
        payload.update(extra_triggers)
    response["HX-Trigger"] = json.dumps(payload)
    return response


def render_oob_list_response(
    request,
    *,
    table_template: str,
    target_id: str,
    context_object_name: str,
    queryset,
    paginate_by: int,
    base_url: str,
    toast_message: str,
    toast_level: str = "success",
    extra_triggers: dict | None = None,
    extra_context: dict | None = None,
) -> HttpResponse:
    """Render an OOB table swap + KPI OOB update + HX-Trigger toast."""
    paginator = Paginator(queryset, paginate_by)
    page_obj = paginator.get_page(1)
    context = {
        context_object_name: page_obj.object_list,
        "object_list": page_obj.object_list,
        "paginator": paginator,
        "page_obj": page_obj,
        "is_paginated": paginator.num_pages > 1,
        "oob_swap": True,
        "htmx_target_id": target_id,
        "hx_base_url": str(base_url),
        "table_template": table_template,
        "snapshot": get_dashboard_snapshot(),
    }
    if extra_context:
        context.update(extra_context)

    response = render(
        request,
        "bar/partials/drawer_success_oob.html",
        context,
    )
    triggers = {"closeDrawer": True}
    if extra_triggers:
        triggers.update(extra_triggers)
    return add_htmx_toast(
        response,
        level=toast_level,
        message=toast_message,
        extra_triggers=triggers,
    )


class HtmxPartialTemplateMixin:
    """Use partial_template_name when handling non-boosted HTMX requests."""

    partial_template_name: str | None = None

    def get_template_names(self):
        if is_htmx_partial(self.request) and self.partial_template_name:
            return [self.partial_template_name]
        return super().get_template_names()


class BaseSearchListView(
    HtmxPartialTemplateMixin,
    LoginRequiredMixin,
    generic.ListView,
):
    """Paginated list view with optional search form and HTMX partial swap."""

    paginate_by = 10
    search_form_class = None
    search_field = "name"

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        if self.search_form_class:
            search_value = self.request.GET.get(self.search_field, "")
            context["search_form"] = self.search_form_class(
                initial={self.search_field: search_value}
            )
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.search_form_class:
            form = self.search_form_class(self.request.GET)
            if form.is_valid():
                query = form.cleaned_data.get(self.search_field, "").strip()
                if query:
                    lookup = f"{self.search_field}__icontains"
                    return queryset.filter(**{lookup: query})
        return queryset


class AnalyticsCacheInvalidationMixin:
    """Invalidate cached analytics snapshots after successful form saves."""

    def form_valid(self, form):
        response = super().form_valid(form)
        invalidate_analytics_cache()
        return response


class HtmxDrawerFormMixin:
    """Serve drawer partials and OOB table/KPI updates on HTMX form views."""

    drawer_template_name = "bar/partials/drawer_form.html"
    drawer_title = ""
    drawer_submit_label = "Save"
    oob_table_template: str | None = None
    oob_target_id: str | None = None
    oob_context_object_name = "object_list"
    oob_paginate_by = 10
    oob_event_name: str | None = None
    success_toast_message = "Saved successfully."

    def get_template_names(self):
        if is_htmx_partial(self.request):
            return [self.drawer_template_name]
        return super().get_template_names()

    def get_drawer_title(self) -> str:
        return self.drawer_title

    def get_oob_queryset(self):
        return self.model.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["drawer_title"] = self.get_drawer_title()
        context["drawer_submit_label"] = self.drawer_submit_label
        context["form_action"] = self.request.path
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        if (
            is_htmx_partial(self.request)
            and self.oob_table_template
            and self.oob_target_id
        ):
            invalidate_analytics_cache()
            extra_triggers = (
                {self.oob_event_name: True} if self.oob_event_name else None
            )
            return render_oob_list_response(
                self.request,
                table_template=self.oob_table_template,
                target_id=self.oob_target_id,
                context_object_name=self.oob_context_object_name,
                queryset=self.get_oob_queryset(),
                paginate_by=self.oob_paginate_by,
                base_url=self.success_url,
                toast_message=self.success_toast_message,
                extra_triggers=extra_triggers,
            )
        return response

    def form_invalid(self, form):
        response = super().form_invalid(form)
        if is_htmx_partial(self.request):
            return add_htmx_toast(
                response,
                level="error",
                message="Please correct the form errors.",
            )
        return response


class ProtectedDeleteMixin:
    """Catch ProtectedError on delete and respond with toast or redirect."""

    protected_error_message = (
        "Cannot delete this item because it is referenced by other records."
    )
    oob_table_template: str | None = None
    oob_target_id: str | None = None
    oob_context_object_name = "object_list"
    oob_paginate_by = 10
    oob_event_name: str | None = None

    def get_oob_queryset(self):
        return self.model.objects.all()

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, self.protected_error_message)
            if is_htmx(self.request):
                error_response = HttpResponse(
                    self.protected_error_message,
                    status=409,
                    content_type="text/plain; charset=utf-8",
                )
                return add_htmx_toast(
                    error_response,
                    level="error",
                    message=self.protected_error_message,
                )
            return redirect(self.success_url)

        invalidate_analytics_cache()
        if (
            is_htmx_partial(self.request)
            and self.oob_table_template
            and self.oob_target_id
        ):
            extra_triggers = (
                {self.oob_event_name: True} if self.oob_event_name else None
            )
            return render_oob_list_response(
                self.request,
                table_template=self.oob_table_template,
                target_id=self.oob_target_id,
                context_object_name=self.oob_context_object_name,
                queryset=self.get_oob_queryset(),
                paginate_by=self.oob_paginate_by,
                base_url=self.success_url,
                toast_message="Deleted successfully.",
                extra_triggers=extra_triggers,
            )
        return response
