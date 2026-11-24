from django.http import HttpResponse
from django.shortcuts import render
from django.views import generic

from bar.forms import AuditLogFilterForm
from bar.models import AuditLog
from bar.permissions import MANAGER_ROLES, RoleRequiredMixin, role_required
from bar.services.analytics import (
    VALID_PERIODS,
    export_analytics_csv,
    get_analytics_report,
    normalize_period,
)
from bar.views.mixins import HtmxPartialTemplateMixin, is_htmx_partial


@role_required(*MANAGER_ROLES)
def analytics_dashboard(request):
    """Render the financial and stock In-vs-Out analytics report."""
    period = normalize_period(request.GET.get("period"))
    report = get_analytics_report(period)
    active_days = tuple(
        day_point
        for day_point in reversed(report.daily_series)
        if (
            day_point.revenue > 0
            or day_point.stock_in_cost > 0
            or day_point.loss_cost > 0
            or day_point.orders_count > 0
        )
    )
    template_name = (
        "bar/partials/analytics_content.html"
        if is_htmx_partial(request)
        else "bar/analytics.html"
    )
    return render(
        request,
        template_name,
        {
            "report": report,
            "period": period,
            "valid_periods": VALID_PERIODS,
            "active_days": active_days,
        },
    )


@role_required(*MANAGER_ROLES)
def analytics_export_csv(request):
    """Download the period analytics report and ledger as a safe CSV."""
    period = normalize_period(request.GET.get("period"))
    csv_content = export_analytics_csv(period)
    response = HttpResponse(
        csv_content,
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="bar-analytics-{period}.csv"'
    )
    return response


class AuditLogListView(
    HtmxPartialTemplateMixin,
    RoleRequiredMixin,
    generic.ListView,
):
    allowed_roles = MANAGER_ROLES
    model = AuditLog
    context_object_name = "audit_logs"
    template_name = "bar/audit_log_list.html"
    partial_template_name = "bar/partials/audit_log_table.html"
    paginate_by = 20

    def get_queryset(self):
        queryset = AuditLog.objects.select_related("actor")
        form = AuditLogFilterForm(self.request.GET)
        if form.is_valid():
            action = form.cleaned_data.get("action", "").strip()
            actor = form.cleaned_data.get("actor")
            if action:
                queryset = queryset.filter(action__icontains=action)
            if actor is not None:
                queryset = queryset.filter(actor=actor)
        return queryset

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        context["filter_form"] = AuditLogFilterForm(self.request.GET)
        return context
