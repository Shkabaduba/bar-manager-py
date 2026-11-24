from collections.abc import Iterable
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io

from django.core.cache import cache
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from bar.models import (
    BarIngredient,
    Bartender,
    Drink,
    DrinksCategory,
    Order,
    OrderItem,
    StockMovement,
)
from bar.services.cache import get_analytics_cache_version

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_PLACES = Decimal("0.01")
VALID_PERIODS = ("today", "7d", "30d")
PERIOD_DAYS = {"today": 1, "7d": 7, "30d": 30}
ANALYTICS_CACHE_TTL_SECONDS = 300
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class DashboardSnapshot:
    """Cached KPI snapshot displayed on the main dashboard."""

    num_drinks: int
    num_active_drinks: int
    num_categories: int
    num_suppliers: int
    num_bartenders: int
    active_orders: int
    paid_orders_today: int
    revenue_today: Decimal
    cogs_today: Decimal
    gross_profit_today: Decimal
    out_of_stock_ingredients: int
    low_stock_ingredients: int
    stock_total_value: Decimal


@dataclass(frozen=True)
class DailySeriesPoint:
    """Single day bucket for revenue, COGS, stock receipts, and losses."""

    day: date
    label: str
    revenue: Decimal
    cogs: Decimal
    stock_in_cost: Decimal
    loss_cost: Decimal
    orders_count: int


@dataclass(frozen=True)
class TopDrinkMetric:
    """Top-performing drink aggregated by gross margin over a period."""

    drink_id: int
    drink_name: str
    category_name: str
    portions_sold: int
    revenue: Decimal
    cogs: Decimal
    gross_margin: Decimal
    margin_pct: Decimal


@dataclass(frozen=True)
class BartenderRankingMetric:
    """Bartender performance aggregated over closed orders."""

    bartender_id: int
    username: str
    full_name: str
    orders_closed: int
    revenue: Decimal
    avg_check: Decimal


@dataclass(frozen=True)
class AnalyticsReport:
    """Complete In vs Out financial & inventory report for a period."""

    period: str
    start_date: date
    end_date: date
    paid_orders_count: int
    cancelled_orders_count: int
    force_closed_orders_count: int
    revenue: Decimal
    cogs: Decimal
    gross_margin: Decimal
    food_cost_pct: Decimal
    stock_in_cost: Decimal
    stock_out_order_cost: Decimal
    writeoff_loss: Decimal
    adjustment_shortage_loss: Decimal
    adjustment_surplus_gain: Decimal
    total_losses: Decimal
    net_margin_after_losses: Decimal
    current_stock_value: Decimal
    daily_series: tuple[DailySeriesPoint, ...]
    top_drinks: tuple[TopDrinkMetric, ...]
    bartender_ranking: tuple[BartenderRankingMetric, ...]


def _round_money(amount: Decimal | None) -> Decimal:
    if amount is None:
        return Decimal("0.00")
    return Decimal(amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def normalize_period(period: str | None) -> str:
    """Normalize user-supplied period query param into a supported window."""
    if period in VALID_PERIODS:
        return period
    return "7d"


def _resolve_period_bounds(
    period: str,
) -> tuple[date, date, datetime, datetime]:
    current_tz = timezone.get_current_timezone()
    end_date = timezone.localdate()
    num_days = PERIOD_DAYS[period]
    start_date = end_date - timedelta(days=num_days - 1)
    start_dt = timezone.make_aware(
        datetime.combine(start_date, time.min),
        current_tz,
    )
    end_dt = timezone.make_aware(
        datetime.combine(end_date + timedelta(days=1), time.min),
        current_tz,
    )
    return start_date, end_date, start_dt, end_dt


def _compute_current_stock_value() -> Decimal:
    value_expr = ExpressionWrapper(
        F("stock_quantity") * F("cost_per_unit"),
        output_field=DecimalField(max_digits=16, decimal_places=4),
    )
    total = BarIngredient.objects.aggregate(total=Sum(value_expr))["total"]
    return _round_money(total)


def _build_daily_series(
    start_date: date,
    end_date: date,
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[DailySeriesPoint, ...]:
    current_tz = timezone.get_current_timezone()
    order_rows = (
        Order.objects.filter(
            status=Order.Status.PAID,
            paid_at__gte=start_dt,
            paid_at__lt=end_dt,
        )
        .annotate(day=TruncDate("paid_at", tzinfo=current_tz))
        .values("day")
        .annotate(
            orders_count=Count("id"),
            revenue=Sum("total_revenue_snapshot"),
            cogs=Sum("total_cost_snapshot"),
        )
    )
    orders_by_day = {row["day"]: row for row in order_rows}

    movement_rows = (
        StockMovement.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        .annotate(day=TruncDate("created_at", tzinfo=current_tz))
        .values("day")
        .annotate(
            stock_in_cost=Sum(
                "total_cost",
                filter=Q(movement_type=StockMovement.MovementType.IN),
            ),
            loss_cost=Sum(
                "total_cost",
                filter=(
                    Q(movement_type=StockMovement.MovementType.WRITEOFF)
                    | Q(
                        movement_type=StockMovement.MovementType.ADJUSTMENT,
                        quantity_delta__lt=ZERO,
                    )
                ),
            ),
        )
    )
    movements_by_day = {row["day"]: row for row in movement_rows}

    points: list[DailySeriesPoint] = []
    current_day = start_date
    while current_day <= end_date:
        order_row = orders_by_day.get(current_day, {})
        movement_row = movements_by_day.get(current_day, {})
        points.append(
            DailySeriesPoint(
                day=current_day,
                label=current_day.strftime("%d.%m"),
                revenue=_round_money(order_row.get("revenue")),
                cogs=_round_money(order_row.get("cogs")),
                stock_in_cost=_round_money(movement_row.get("stock_in_cost")),
                loss_cost=_round_money(movement_row.get("loss_cost")),
                orders_count=order_row.get("orders_count") or 0,
            )
        )
        current_day += timedelta(days=1)
    return tuple(points)


def _build_top_drinks(
    start_dt: datetime,
    end_dt: datetime,
    limit: int = 5,
) -> tuple[TopDrinkMetric, ...]:
    revenue_expr = ExpressionWrapper(
        F("unit_price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    cogs_expr = ExpressionWrapper(
        F("unit_cost_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=4),
    )
    rows = (
        OrderItem.objects.filter(
            order__status=Order.Status.PAID,
            order__paid_at__gte=start_dt,
            order__paid_at__lt=end_dt,
        )
        .values("drink_id", "drink__name", "drink__category__name")
        .annotate(
            portions_sold=Sum("quantity"),
            revenue=Sum(revenue_expr),
            cogs=Sum(cogs_expr),
        )
    )

    metrics: list[TopDrinkMetric] = []
    for row in rows:
        revenue = _round_money(row["revenue"])
        cogs = _round_money(row["cogs"])
        gross_margin = _round_money(revenue - cogs)
        margin_pct = (
            _round_money((gross_margin / revenue) * HUNDRED)
            if revenue > ZERO
            else Decimal("0.00")
        )
        metrics.append(
            TopDrinkMetric(
                drink_id=row["drink_id"],
                drink_name=row["drink__name"],
                category_name=row["drink__category__name"],
                portions_sold=row["portions_sold"] or 0,
                revenue=revenue,
                cogs=cogs,
                gross_margin=gross_margin,
                margin_pct=margin_pct,
            )
        )

    metrics.sort(
        key=lambda metric: (
            -metric.gross_margin,
            -metric.portions_sold,
            metric.drink_name,
        )
    )
    return tuple(metrics[:limit])


def _build_bartender_ranking(
    start_dt: datetime,
    end_dt: datetime,
) -> tuple[BartenderRankingMetric, ...]:
    rows = (
        Order.objects.filter(
            status=Order.Status.PAID,
            paid_at__gte=start_dt,
            paid_at__lt=end_dt,
        )
        .values(
            "bartender_id",
            "bartender__username",
            "bartender__first_name",
            "bartender__last_name",
            "closed_by_id",
            "closed_by__username",
            "closed_by__first_name",
            "closed_by__last_name",
        )
        .annotate(
            orders_count=Count("id"),
            revenue=Sum("total_revenue_snapshot"),
        )
    )

    merged: dict[int, dict[str, object]] = {}
    for row in rows:
        if row["bartender_id"] is not None:
            credited_id = row["bartender_id"]
            username = row["bartender__username"]
            first_name = row["bartender__first_name"] or ""
            last_name = row["bartender__last_name"] or ""
        elif row["closed_by_id"] is not None:
            credited_id = row["closed_by_id"]
            username = row["closed_by__username"]
            first_name = row["closed_by__first_name"] or ""
            last_name = row["closed_by__last_name"] or ""
        else:
            continue

        if credited_id not in merged:
            full_name = f"{first_name} {last_name}".strip() or username
            merged[credited_id] = {
                "username": username,
                "full_name": full_name,
                "orders_closed": 0,
                "revenue": ZERO,
            }
        bucket = merged[credited_id]
        bucket["orders_closed"] += row["orders_count"] or 0
        bucket["revenue"] += row["revenue"] or ZERO

    ranking: list[BartenderRankingMetric] = []
    for bartender_id, bucket in merged.items():
        orders_closed = int(bucket["orders_closed"])
        revenue = _round_money(bucket["revenue"])
        avg_check = (
            _round_money(revenue / orders_closed)
            if orders_closed > 0
            else Decimal("0.00")
        )
        ranking.append(
            BartenderRankingMetric(
                bartender_id=bartender_id,
                username=str(bucket["username"]),
                full_name=str(bucket["full_name"]),
                orders_closed=orders_closed,
                revenue=revenue,
                avg_check=avg_check,
            )
        )

    ranking.sort(
        key=lambda metric: (
            -metric.revenue,
            -metric.orders_closed,
            metric.username,
        )
    )
    return tuple(ranking)


def get_dashboard_snapshot() -> DashboardSnapshot:
    """Return cached dashboard KPIs, automatically scoped by cache version."""
    today = timezone.localdate()
    version = get_analytics_cache_version()
    cache_key = f"bar:dashboard:v{version}:{today.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    _, _, today_start, tomorrow_start = _resolve_period_bounds("today")
    today_agg = Order.objects.filter(
        status=Order.Status.PAID,
        paid_at__gte=today_start,
        paid_at__lt=tomorrow_start,
    ).aggregate(
        paid_count=Count("id"),
        revenue=Sum("total_revenue_snapshot"),
        cogs=Sum("total_cost_snapshot"),
    )
    revenue_today = _round_money(today_agg["revenue"])
    cogs_today = _round_money(today_agg["cogs"])

    from bar.models import BarSupplier

    snapshot = DashboardSnapshot(
        num_drinks=Drink.objects.count(),
        num_active_drinks=Drink.objects.filter(is_active=True).count(),
        num_categories=DrinksCategory.objects.count(),
        num_suppliers=BarSupplier.objects.filter(is_active=True).count(),
        num_bartenders=Bartender.objects.filter(is_active=True).count(),
        active_orders=Order.objects.filter(
            status__in=[Order.Status.OPEN, Order.Status.IN_PROGRESS]
        ).count(),
        paid_orders_today=today_agg["paid_count"] or 0,
        revenue_today=revenue_today,
        cogs_today=cogs_today,
        gross_profit_today=_round_money(revenue_today - cogs_today),
        out_of_stock_ingredients=BarIngredient.objects.filter(
            stock_quantity=ZERO
        ).count(),
        low_stock_ingredients=BarIngredient.objects.filter(
            stock_quantity__gt=ZERO,
            min_stock_threshold__gt=ZERO,
            stock_quantity__lte=F("min_stock_threshold"),
        ).count(),
        stock_total_value=_compute_current_stock_value(),
    )
    cache.set(cache_key, snapshot, timeout=ANALYTICS_CACHE_TTL_SECONDS)
    return snapshot


def get_analytics_report(period: str | None = "7d") -> AnalyticsReport:
    """Return cached In vs Out financial and inventory report for a period."""
    normalized = normalize_period(period)
    today = timezone.localdate()
    version = get_analytics_cache_version()
    cache_key = f"bar:analytics:v{version}:{normalized}:{today.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start_date, end_date, start_dt, end_dt = _resolve_period_bounds(normalized)
    order_agg = Order.objects.filter(
        status=Order.Status.PAID,
        paid_at__gte=start_dt,
        paid_at__lt=end_dt,
    ).aggregate(
        paid_count=Count("id"),
        force_closed_count=Count("id", filter=Q(override_by__isnull=False)),
        revenue=Sum("total_revenue_snapshot"),
        cogs=Sum("total_cost_snapshot"),
    )
    cancelled_count = Order.objects.filter(
        status=Order.Status.CANCELLED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    ).count()

    movement_agg = StockMovement.objects.filter(
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    ).aggregate(
        stock_in_cost=Sum(
            "total_cost",
            filter=Q(movement_type=StockMovement.MovementType.IN),
        ),
        stock_out_order_cost=Sum(
            "total_cost",
            filter=Q(movement_type=StockMovement.MovementType.OUT_ORDER),
        ),
        writeoff_loss=Sum(
            "total_cost",
            filter=Q(movement_type=StockMovement.MovementType.WRITEOFF),
        ),
        adjustment_shortage_loss=Sum(
            "total_cost",
            filter=Q(
                movement_type=StockMovement.MovementType.ADJUSTMENT,
                quantity_delta__lt=ZERO,
            ),
        ),
        adjustment_surplus_gain=Sum(
            "total_cost",
            filter=Q(
                movement_type=StockMovement.MovementType.ADJUSTMENT,
                quantity_delta__gt=ZERO,
            ),
        ),
    )

    revenue = _round_money(order_agg["revenue"])
    cogs = _round_money(order_agg["cogs"])
    gross_margin = _round_money(revenue - cogs)
    food_cost_pct = (
        _round_money((cogs / revenue) * HUNDRED)
        if revenue > ZERO
        else Decimal("0.00")
    )
    writeoff_loss = _round_money(movement_agg["writeoff_loss"])
    shortage_loss = _round_money(movement_agg["adjustment_shortage_loss"])
    total_losses = _round_money(writeoff_loss + shortage_loss)

    report = AnalyticsReport(
        period=normalized,
        start_date=start_date,
        end_date=end_date,
        paid_orders_count=order_agg["paid_count"] or 0,
        cancelled_orders_count=cancelled_count,
        force_closed_orders_count=order_agg["force_closed_count"] or 0,
        revenue=revenue,
        cogs=cogs,
        gross_margin=gross_margin,
        food_cost_pct=food_cost_pct,
        stock_in_cost=_round_money(movement_agg["stock_in_cost"]),
        stock_out_order_cost=_round_money(
            movement_agg["stock_out_order_cost"]
        ),
        writeoff_loss=writeoff_loss,
        adjustment_shortage_loss=shortage_loss,
        adjustment_surplus_gain=_round_money(
            movement_agg["adjustment_surplus_gain"]
        ),
        total_losses=total_losses,
        net_margin_after_losses=_round_money(gross_margin - total_losses),
        current_stock_value=_compute_current_stock_value(),
        daily_series=_build_daily_series(
            start_date,
            end_date,
            start_dt,
            end_dt,
        ),
        top_drinks=_build_top_drinks(start_dt, end_dt),
        bartender_ranking=_build_bartender_ranking(start_dt, end_dt),
    )
    cache.set(cache_key, report, timeout=ANALYTICS_CACHE_TTL_SECONDS)
    return report


def sanitize_csv_cell(cell_value: object) -> str:
    """Neutralize spreadsheet formula injection while preserving numbers."""
    if cell_value is None:
        return ""
    if isinstance(cell_value, Decimal) or (
        isinstance(cell_value, int) and not isinstance(cell_value, bool)
    ):
        return str(cell_value)
    text = str(cell_value)
    if text.startswith(CSV_FORMULA_PREFIXES) or text.lstrip(" ").startswith(
        CSV_FORMULA_PREFIXES
    ):
        return f"'{text}"
    return text


def _write_safe_row(writer, row: Iterable[object]) -> None:
    writer.writerow([sanitize_csv_cell(cell) for cell in row])


def export_analytics_csv(period: str | None = "7d") -> str:
    """Export period summary, series, rankings, and ledger to safe CSV."""
    report = get_analytics_report(period)
    _, _, start_dt, end_dt = _resolve_period_bounds(report.period)
    movements = (
        StockMovement.objects.filter(
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        .select_related("ingredient", "performed_by")
        .order_by("-created_at", "-id")
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    _write_safe_row(writer, ["Summary", report.period])
    _write_safe_row(writer, ["Metric", "Value"])
    summary_rows = [
        ("Start Date", report.start_date.isoformat()),
        ("End Date", report.end_date.isoformat()),
        ("Paid Orders", report.paid_orders_count),
        ("Cancelled Orders", report.cancelled_orders_count),
        ("Force Closed Orders", report.force_closed_orders_count),
        ("Revenue", report.revenue),
        ("COGS", report.cogs),
        ("Gross Margin", report.gross_margin),
        ("Food Cost %", report.food_cost_pct),
        ("Stock In Cost", report.stock_in_cost),
        ("Stock Out Order Cost", report.stock_out_order_cost),
        ("Write-off Loss", report.writeoff_loss),
        ("Adjustment Shortage Loss", report.adjustment_shortage_loss),
        ("Adjustment Surplus Gain", report.adjustment_surplus_gain),
        ("Total Losses", report.total_losses),
        ("Net Margin After Losses", report.net_margin_after_losses),
        ("Current Stock Value", report.current_stock_value),
    ]
    for metric_name, metric_value in summary_rows:
        _write_safe_row(writer, [metric_name, metric_value])

    _write_safe_row(writer, [])
    _write_safe_row(
        writer,
        ["Date", "Orders", "Revenue", "COGS", "Stock In Cost", "Losses"],
    )
    for point in report.daily_series:
        _write_safe_row(
            writer,
            [
                point.day.isoformat(),
                point.orders_count,
                point.revenue,
                point.cogs,
                point.stock_in_cost,
                point.loss_cost,
            ],
        )

    _write_safe_row(writer, [])
    _write_safe_row(
        writer,
        [
            "Drink",
            "Category",
            "Portions Sold",
            "Revenue",
            "COGS",
            "Gross Margin",
            "Margin %",
        ],
    )
    for drink_metric in report.top_drinks:
        _write_safe_row(
            writer,
            [
                drink_metric.drink_name,
                drink_metric.category_name,
                drink_metric.portions_sold,
                drink_metric.revenue,
                drink_metric.cogs,
                drink_metric.gross_margin,
                drink_metric.margin_pct,
            ],
        )

    _write_safe_row(writer, [])
    _write_safe_row(
        writer,
        [
            "Username",
            "Full Name",
            "Orders Closed",
            "Revenue",
            "Average Check",
        ],
    )
    for staff_metric in report.bartender_ranking:
        _write_safe_row(
            writer,
            [
                staff_metric.username,
                staff_metric.full_name,
                staff_metric.orders_closed,
                staff_metric.revenue,
                staff_metric.avg_check,
            ],
        )

    _write_safe_row(writer, [])
    _write_safe_row(
        writer,
        [
            "Timestamp",
            "Type",
            "Ingredient",
            "Delta",
            "Unit",
            "Balance After",
            "Total Cost",
            "Reason",
            "Performed By",
        ],
    )
    for movement in movements:
        _write_safe_row(
            writer,
            [
                timezone.localtime(movement.created_at).isoformat(),
                movement.movement_type,
                movement.ingredient.name,
                movement.quantity_delta,
                movement.ingredient.unit,
                movement.balance_after,
                movement.total_cost,
                movement.reason,
                movement.performed_by.username
                if movement.performed_by
                else "",
            ],
        )

    return buffer.getvalue()
