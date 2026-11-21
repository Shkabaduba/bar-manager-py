from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import generic
from django.views.decorators.http import require_POST

from bar.forms import OrderCreateForm, OrderForceCloseForm
from bar.middleware import get_client_ip
from bar.models import Drink, Order
from bar.permissions import htmx_forbidden_response
from bar.services.analytics import get_dashboard_snapshot
from bar.services.costing import calculate_drinks_costing_map
from bar.services.exceptions import (
    BarServiceError,
    InsufficientStockError,
    OrderAlreadyClosedError,
)
from bar.services.orders import (
    add_order_item,
    cancel_order,
    close_and_pay_order,
    create_order,
    remove_order_item,
    set_order_item,
    toggle_assign_order as toggle_assign_order_service,
)
from bar.views.mixins import (
    HtmxPartialTemplateMixin,
    add_htmx_toast,
    is_htmx,
    is_htmx_partial,
)

FINAL_ORDER_STATUSES = frozenset({
    Order.Status.PAID,
    Order.Status.CANCELLED,
})


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None
    stripped = str(raw_value).strip()
    if not stripped:
        return None
    return int(stripped)


def _order_detail_queryset():
    return Order.objects.select_related(
        "bartender",
        "closed_by",
        "override_by",
    ).prefetch_related(
        "drinks__category",
        "items__drink__category",
    )


def _build_order_pos_context(
    order: Order,
    *,
    deficits=None,
    force_close_form: OrderForceCloseForm | None = None,
) -> dict:
    order_items = list(
        order.items.select_related("drink__category").order_by("id")
    )
    if order.status == Order.Status.PAID:
        order_total = order.total_revenue_snapshot
    else:
        order_total = sum(
            (
                (order_item.unit_price_snapshot or order_item.drink.price)
                * order_item.quantity
                for order_item in order_items
            ),
            Decimal("0.00"),
        )

    menu_drinks = list(
        Drink.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related("recipe_items__ingredient")
        .order_by("category__name", "name")
    )
    menu_costing_map = calculate_drinks_costing_map(menu_drinks)
    for drink in menu_drinks:
        drink.costing = menu_costing_map[drink.pk]

    is_order_mutable = (
        order.status not in FINAL_ORDER_STATUSES and not order.is_paid
    )
    return {
        "order": order,
        "order_items": order_items,
        "order_total": order_total,
        "menu_drinks": menu_drinks,
        "menu_costing_map": menu_costing_map,
        "is_order_mutable": is_order_mutable,
        "deficits": tuple(deficits) if deficits else (),
        "force_close_form": force_close_form
        or OrderForceCloseForm(initial={"expected_version": order.version}),
    }


def _render_order_pos_htmx(
    request,
    order_id: int,
    *,
    toast_level: str,
    toast_message: str,
    deficits=None,
    force_close_form: OrderForceCloseForm | None = None,
    status: int = 200,
    include_kpi_oob: bool = False,
) -> HttpResponse:
    order = get_object_or_404(_order_detail_queryset(), pk=order_id)
    context = _build_order_pos_context(
        order,
        deficits=deficits,
        force_close_form=force_close_form,
    )
    context["include_kpi_oob"] = include_kpi_oob
    context["snapshot"] = (
        get_dashboard_snapshot() if include_kpi_oob else None
    )
    response = render(
        request,
        "bar/partials/order_pos_htmx_response.html",
        context,
        status=status,
    )
    if status >= 400:
        response["HX-Retarget"] = "#order-pos-workspace"
        response["HX-Reswap"] = "outerHTML"
    return add_htmx_toast(
        response,
        level=toast_level,
        message=toast_message,
    )


class OrderListView(
    HtmxPartialTemplateMixin,
    LoginRequiredMixin,
    generic.ListView,
):
    model = Order
    context_object_name = "order_list"
    template_name = "bar/order_list.html"
    partial_template_name = "bar/partials/order_table.html"
    paginate_by = 10

    def get_queryset(self):
        line_total_expr = ExpressionWrapper(
            F("items__quantity") * F("items__unit_price_snapshot"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        queryset = (
            Order.objects.select_related("bartender", "closed_by")
            .annotate(
                items_count=Coalesce(Sum("items__quantity"), 0),
                calculated_total=Coalesce(
                    Sum(line_total_expr),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(
                        max_digits=14,
                        decimal_places=2,
                    ),
                ),
            )
            .order_by("-created_at")
        )
        status_param = self.request.GET.get("status", "").strip()
        if status_param == "ACTIVE":
            queryset = queryset.filter(
                status__in=[Order.Status.OPEN, Order.Status.IN_PROGRESS]
            )
        elif status_param in Order.Status.values:
            queryset = queryset.filter(status=status_param)

        if self.request.GET.get("mine", "").strip() == "1":
            queryset = queryset.filter(bartender=self.request.user)
        return queryset

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        context["status_choices"] = Order.Status.choices
        context["selected_status"] = self.request.GET.get("status", "")
        context["create_order_form"] = OrderCreateForm()
        return context


@login_required
def order_create_view(request):
    """Create a new table order and redirect to its POS detail screen."""
    form = OrderCreateForm(request.POST or None)
    htmx_partial = is_htmx_partial(request)

    if request.method == "POST":
        if form.is_valid():
            bartender = (
                request.user
                if form.cleaned_data.get("assign_to_me")
                else None
            )
            order = create_order(
                table_number=form.cleaned_data["table_number"],
                bartender=bartender,
            )
            created_message = (
                f"Order #{order.pk} created for table {order.table_number}."
            )
            messages.success(request, created_message)
            detail_url = reverse("bar:order-detail", kwargs={"pk": order.pk})
            if htmx_partial:
                response = HttpResponse(status=204)
                response["HX-Redirect"] = detail_url
                return add_htmx_toast(
                    response,
                    level="success",
                    message=created_message,
                    extra_triggers={"closeDrawer": True},
                )
            return redirect(detail_url)

    if htmx_partial:
        response = render(
            request,
            "bar/partials/drawer_form.html",
            {
                "form": form,
                "drawer_title": "Create Order",
                "drawer_submit_label": "Create Order",
                "form_action": request.path,
            },
        )
        if request.method == "POST":
            return add_htmx_toast(
                response,
                level="error",
                message="Please correct the form errors.",
            )
        return response

    return render(request, "bar/order_form.html", {"form": form})


class OrderDetailView(LoginRequiredMixin, generic.DetailView):
    model = Order
    template_name = "bar/order_detail.html"

    def get_queryset(self):
        return _order_detail_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_build_order_pos_context(self.object))
        return context


@login_required
@require_POST
def toggle_assign_order(request, pk):
    """Claim or release an order for the current bartender."""
    htmx_partial = is_htmx_partial(request)
    try:
        _, outcome = toggle_assign_order_service(
            order_id=pk,
            actor=request.user,
        )
    except Order.DoesNotExist as exc:
        raise Http404("Order not found.") from exc
    except OrderAlreadyClosedError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
        return redirect("bar:order-detail", pk=pk)

    if outcome == "taken_by_other":
        warning_text = "Order has been assigned by other Bartender"
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="warning",
                toast_message=warning_text,
            )
        messages.warning(request, warning_text)
    elif htmx_partial:
        toast_text = (
            f"Order #{pk} assigned to you."
            if outcome == "assigned"
            else f"Order #{pk} released."
        )
        return _render_order_pos_htmx(
            request,
            pk,
            toast_level="success",
            toast_message=toast_text,
        )
    return redirect("bar:order-detail", pk=pk)


@login_required
@require_POST
def order_add_item(request, pk):
    """Increment or add a drink line inside a mutable order."""
    htmx_partial = is_htmx_partial(request)
    try:
        drink_id = int(request.POST.get("drink_id", ""))
        delta = _parse_optional_int(request.POST.get("delta")) or 1
        expected_version = _parse_optional_int(
            request.POST.get("expected_version")
        )
    except ValueError:
        error_text = "Invalid drink or quantity parameter."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=error_text,
            )
        messages.error(request, error_text)
        return redirect("bar:order-detail", pk=pk)

    try:
        add_order_item(
            order_id=pk,
            drink_id=drink_id,
            delta=delta,
            expected_version=expected_version,
        )
    except (Order.DoesNotExist, Drink.DoesNotExist) as exc:
        raise Http404("Order or drink not found.") from exc
    except BarServiceError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
    else:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="success",
                toast_message="Order item updated.",
            )
    return redirect("bar:order-detail", pk=pk)


@login_required
@require_POST
def order_set_item(request, pk, drink_id):
    """Set exact drink quantity inside a mutable order."""
    htmx_partial = is_htmx_partial(request)
    try:
        quantity = int(request.POST.get("quantity", ""))
        expected_version = _parse_optional_int(
            request.POST.get("expected_version")
        )
    except ValueError:
        error_text = "Invalid quantity parameter."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=error_text,
            )
        messages.error(request, error_text)
        return redirect("bar:order-detail", pk=pk)

    try:
        set_order_item(
            order_id=pk,
            drink_id=drink_id,
            quantity=quantity,
            expected_version=expected_version,
        )
    except (Order.DoesNotExist, Drink.DoesNotExist) as exc:
        raise Http404("Order or drink not found.") from exc
    except BarServiceError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
    else:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="success",
                toast_message="Order quantity updated.",
            )
    return redirect("bar:order-detail", pk=pk)


@login_required
@require_POST
def order_remove_item(request, pk, drink_id):
    """Remove a drink line from a mutable order."""
    htmx_partial = is_htmx_partial(request)
    try:
        expected_version = _parse_optional_int(
            request.POST.get("expected_version")
        )
    except ValueError:
        error_text = "Invalid order version."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=error_text,
            )
        messages.error(request, error_text)
        return redirect("bar:order-detail", pk=pk)

    try:
        remove_order_item(
            order_id=pk,
            drink_id=drink_id,
            expected_version=expected_version,
        )
    except Order.DoesNotExist as exc:
        raise Http404("Order not found.") from exc
    except BarServiceError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
    else:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="success",
                toast_message="Item removed from order.",
            )
    return redirect("bar:order-detail", pk=pk)


@login_required
@require_POST
def order_pay(request, pk):
    """Close and pay an order with strict stop-list or manager override."""
    htmx_partial = is_htmx_partial(request)
    force_override = request.POST.get("force_override") in (
        "1",
        "true",
        "True",
        "on",
    )
    try:
        expected_version = _parse_optional_int(
            request.POST.get("expected_version")
        )
    except ValueError:
        error_text = "Invalid order version."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=error_text,
            )
        messages.error(request, error_text)
        return redirect("bar:order-detail", pk=pk)

    override_reason = ""
    if force_override:
        if not request.user.can_force_close:
            return htmx_forbidden_response(
                request,
                "Only managers and owners can force-close orders "
                "with deficits.",
            )
        force_form = OrderForceCloseForm(request.POST)
        if not force_form.is_valid():
            reason_error = "Please provide a valid override reason."
            if htmx_partial:
                return _render_order_pos_htmx(
                    request,
                    pk,
                    toast_level="error",
                    toast_message=reason_error,
                    force_close_form=force_form,
                    status=400,
                )
            order = get_object_or_404(_order_detail_queryset(), pk=pk)
            messages.error(request, reason_error)
            context = _build_order_pos_context(
                order,
                force_close_form=force_form,
            )
            return render(
                request,
                "bar/order_detail.html",
                context,
                status=400,
            )
        override_reason = force_form.cleaned_data["override_reason"]
        if force_form.cleaned_data.get("expected_version") is not None:
            expected_version = force_form.cleaned_data["expected_version"]

    try:
        close_and_pay_order(
            order_id=pk,
            actor=request.user,
            force_override=force_override,
            override_reason=override_reason,
            expected_version=expected_version,
            ip_address=get_client_ip(request),
        )
    except Order.DoesNotExist as exc:
        raise Http404("Order not found.") from exc
    except PermissionDenied as exc:
        return htmx_forbidden_response(request, str(exc))
    except InsufficientStockError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="warning",
                toast_message=str(exc),
                deficits=exc.deficits,
                status=409,
            )
        order = get_object_or_404(_order_detail_queryset(), pk=pk)
        messages.warning(request, str(exc))
        context = _build_order_pos_context(order, deficits=exc.deficits)
        response = render(
            request,
            "bar/order_detail.html",
            context,
            status=409,
        )
        if is_htmx(request):
            return add_htmx_toast(
                response,
                level="warning",
                message=str(exc),
            )
        return response
    except BarServiceError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
        return redirect("bar:order-detail", pk=pk)

    success_message = f"Order #{pk} paid and stock deducted."
    if htmx_partial:
        return _render_order_pos_htmx(
            request,
            pk,
            toast_level="success",
            toast_message=success_message,
            include_kpi_oob=True,
        )
    messages.success(request, success_message)
    return redirect("bar:order-detail", pk=pk)


@login_required
@require_POST
def order_cancel(request, pk):
    """Cancel an unpaid order and record the cancellation in AuditLog."""
    htmx_partial = is_htmx_partial(request)
    try:
        expected_version = _parse_optional_int(
            request.POST.get("expected_version")
        )
    except ValueError:
        error_text = "Invalid order version."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=error_text,
            )
        messages.error(request, error_text)
        return redirect("bar:order-detail", pk=pk)

    try:
        cancel_order(
            order_id=pk,
            actor=request.user,
            reason=request.POST.get("reason", ""),
            expected_version=expected_version,
            ip_address=get_client_ip(request),
        )
    except Order.DoesNotExist as exc:
        raise Http404("Order not found.") from exc
    except PermissionDenied as exc:
        return htmx_forbidden_response(request, str(exc))
    except BarServiceError as exc:
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="error",
                toast_message=str(exc),
            )
        messages.error(request, str(exc))
    else:
        success_message = f"Order #{pk} cancelled."
        if htmx_partial:
            return _render_order_pos_htmx(
                request,
                pk,
                toast_level="success",
                toast_message=success_message,
                include_kpi_oob=True,
            )
        messages.success(request, success_message)
    return redirect("bar:order-detail", pk=pk)
