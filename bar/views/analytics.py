from decimal import Decimal

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

SVG_WIDTH = 640
SVG_HEIGHT = 200
CHART_PAD_X = 20.0
CHART_USABLE_WIDTH = 600.0
CHART_BASELINE_Y = 172.0
CHART_PLOT_HEIGHT = 148.0


def _bar_rect(
    amount: Decimal,
    scale_peak: Decimal,
    bar_x: float,
    bar_width: float,
) -> dict:
    if amount <= Decimal("0.00"):
        bar_height = 0.0
    else:
        ratio = float(amount / scale_peak)
        bar_height = max(3.0, round(ratio * CHART_PLOT_HEIGHT, 1))
    return {
        "x": round(bar_x, 1),
        "y": round(CHART_BASELINE_Y - bar_height, 1),
        "width": round(bar_width, 1),
        "height": bar_height,
        "amount": amount,
    }


def _build_svg_chart_data(daily_series: tuple) -> dict:
    total_days = len(daily_series)
    if total_days == 0:
        return {
            "viewbox": f"0 0 {SVG_WIDTH} {SVG_HEIGHT}",
            "baseline_y": int(CHART_BASELINE_Y),
            "has_values": False,
            "peak_amount": Decimal("0.00"),
            "bars": [],
        }

    peak_amount = max(
        (
            max(point.revenue, point.stock_in_cost, point.loss_cost)
            for point in daily_series
        ),
        default=Decimal("0.00"),
    )
    scale_peak = peak_amount if peak_amount > Decimal("0.00") else Decimal("1")
    slot_width = CHART_USABLE_WIDTH / total_days
    bar_width = min(14.0, max(3.0, (slot_width * 0.72) / 3.0))
    group_width = bar_width * 3.0 + 4.0

    groups = []
    for day_index, point in enumerate(daily_series):
        slot_x = CHART_PAD_X + day_index * slot_width
        group_x = slot_x + max(0.0, (slot_width - group_width) / 2.0)
        groups.append(
            {
                "label": point.label,
                "label_x": round(slot_x + slot_width / 2.0, 1),
                "show_label": (
                    total_days <= 10
                    or day_index % 5 == 0
                    or day_index == total_days - 1
                ),
                "revenue_bar": _bar_rect(
                    point.revenue,
                    scale_peak,
                    group_x,
                    bar_width,
                ),
                "stock_in_bar": _bar_rect(
                    point.stock_in_cost,
                    scale_peak,
                    group_x + bar_width + 2.0,
                    bar_width,
                ),
                "loss_bar": _bar_rect(
                    point.loss_cost,
                    scale_peak,
                    group_x + (bar_width + 2.0) * 2.0,
                    bar_width,
                ),
            }
        )

    return {
        "viewbox": f"0 0 {SVG_WIDTH} {SVG_HEIGHT}",
        "baseline_y": int(CHART_BASELINE_Y),
        "has_values": peak_amount > Decimal("0.00"),
        "peak_amount": peak_amount,
        "bars": groups,
    }


@role_required(*MANAGER_ROLES)
def analytics_dashboard(request):
    """Render the financial and stock In-vs-Out analytics report."""
    period = normalize_period(request.GET.get("period"))
    report = get_analytics_report(period)
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
            "chart_data": _build_svg_chart_data(report.daily_series),
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
