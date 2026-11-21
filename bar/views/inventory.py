from decimal import Decimal

from django.contrib import messages
from django.db.models import F
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views import generic

from bar.forms import (
    BarIngredientCreateForm,
    BarIngredientUpdateForm,
    BarSupplierForm,
    IngredientSearchForm,
    StockAdjustmentForm,
    StockInForm,
    StockMovementFilterForm,
    StockWriteoffForm,
    SupplierSearchForm,
)
from bar.middleware import get_client_ip
from bar.models import BarIngredient, BarSupplier, StockMovement
from bar.permissions import MANAGER_ROLES, RoleRequiredMixin, role_required
from bar.services.exceptions import BarServiceError, InsufficientStockError
from bar.services.inventory import (
    record_adjustment,
    record_stock_in,
    record_writeoff,
)
from bar.views.mixins import (
    AnalyticsCacheInvalidationMixin,
    BaseSearchListView,
    HtmxDrawerFormMixin,
    HtmxPartialTemplateMixin,
    ProtectedDeleteMixin,
    add_htmx_toast,
    is_htmx_partial,
    render_oob_list_response,
)


class BarSupplierListView(BaseSearchListView):
    model = BarSupplier
    context_object_name = "supplier_list"
    template_name = "bar/supplier_list.html"
    partial_template_name = "bar/partials/supplier_table.html"
    search_form_class = SupplierSearchForm


class SupplierCrudMixin(RoleRequiredMixin):
    allowed_roles = MANAGER_ROLES
    model = BarSupplier
    success_url = reverse_lazy("bar:supplier-list")


class SupplierFormMixin(
    HtmxDrawerFormMixin,
    AnalyticsCacheInvalidationMixin,
    SupplierCrudMixin,
):
    form_class = BarSupplierForm
    template_name = "bar/supplier_form.html"
    oob_table_template = "bar/partials/supplier_table.html"
    oob_target_id = "supplier-list-region"
    oob_context_object_name = "supplier_list"
    oob_event_name = "suppliersChanged"
    success_toast_message = "Supplier saved."


class BarSupplierCreateView(SupplierFormMixin, generic.CreateView):
    drawer_title = "Create Supplier"


class BarSupplierUpdateView(SupplierFormMixin, generic.UpdateView):
    drawer_title = "Update Supplier"


class BarSupplierDeleteView(
    ProtectedDeleteMixin,
    SupplierCrudMixin,
    generic.DeleteView,
):
    template_name = "bar/supplier_confirm_delete.html"
    oob_table_template = "bar/partials/supplier_table.html"
    oob_target_id = "supplier-list-region"
    oob_context_object_name = "supplier_list"
    oob_event_name = "suppliersChanged"


class BarIngredientListView(BaseSearchListView):
    model = BarIngredient
    queryset = BarIngredient.objects.select_related("supplier")
    context_object_name = "ingredient_list"
    template_name = "bar/ingredient_list.html"
    partial_template_name = "bar/partials/ingredient_table.html"
    search_form_class = IngredientSearchForm

    def get_queryset(self):
        queryset = super().get_queryset()
        stock_status = self.request.GET.get("stock_status", "").strip()
        if stock_status == "out":
            return queryset.filter(stock_quantity=Decimal("0.00"))
        if stock_status == "low":
            return queryset.filter(
                stock_quantity__gt=Decimal("0.00"),
                min_stock_threshold__gt=Decimal("0.00"),
                stock_quantity__lte=F("min_stock_threshold"),
            )
        if stock_status == "ok":
            return queryset.filter(stock_quantity__gt=F("min_stock_threshold"))
        return queryset


class IngredientCrudMixin(RoleRequiredMixin):
    allowed_roles = MANAGER_ROLES
    model = BarIngredient
    success_url = reverse_lazy("bar:ingredient-list")


class IngredientFormMixin(
    HtmxDrawerFormMixin,
    AnalyticsCacheInvalidationMixin,
    IngredientCrudMixin,
):
    template_name = "bar/ingredient_form.html"
    oob_table_template = "bar/partials/ingredient_table.html"
    oob_target_id = "ingredient-list-region"
    oob_context_object_name = "ingredient_list"
    oob_event_name = "ingredientsChanged"
    success_toast_message = "Ingredient saved."

    def get_oob_queryset(self):
        return BarIngredient.objects.select_related("supplier")


class BarIngredientCreateView(IngredientFormMixin, generic.CreateView):
    form_class = BarIngredientCreateForm
    drawer_title = "Create Ingredient"


class BarIngredientUpdateView(IngredientFormMixin, generic.UpdateView):
    form_class = BarIngredientUpdateForm
    drawer_title = "Update Ingredient"


class BarIngredientDeleteView(
    ProtectedDeleteMixin,
    IngredientCrudMixin,
    generic.DeleteView,
):
    template_name = "bar/ingredient_confirm_delete.html"
    oob_table_template = "bar/partials/ingredient_table.html"
    oob_target_id = "ingredient-list-region"
    oob_context_object_name = "ingredient_list"
    oob_event_name = "ingredientsChanged"

    def get_oob_queryset(self):
        return BarIngredient.objects.select_related("supplier")


class StockMovementListView(
    HtmxPartialTemplateMixin,
    RoleRequiredMixin,
    generic.ListView,
):
    allowed_roles = MANAGER_ROLES
    model = StockMovement
    context_object_name = "movement_list"
    template_name = "bar/stock_movement_list.html"
    partial_template_name = "bar/partials/stock_movement_table.html"
    paginate_by = 20

    def get_queryset(self):
        queryset = StockMovement.objects.select_related(
            "ingredient",
            "performed_by",
            "order",
        )
        form = StockMovementFilterForm(self.request.GET)
        if form.is_valid():
            movement_type = form.cleaned_data.get("movement_type")
            ingredient = form.cleaned_data.get("ingredient")
            if movement_type:
                queryset = queryset.filter(movement_type=movement_type)
            if ingredient is not None:
                queryset = queryset.filter(ingredient=ingredient)
        return queryset

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        context["filter_form"] = StockMovementFilterForm(self.request.GET)
        return context


def _initial_ingredient(request) -> dict:
    raw_id = request.GET.get("ingredient", "").strip()
    if raw_id.isdigit():
        return {"ingredient": int(raw_id)}
    return {}


def _handle_stock_operation_request(
    request,
    *,
    form_class,
    operation_title: str,
    operation_action: str,
    execute_fn,
    success_prefix: str,
):
    form = form_class(
        request.POST or None,
        initial=_initial_ingredient(request),
    )
    status_code = 200
    htmx_partial = is_htmx_partial(request)
    toast_error_message = None

    if request.method == "POST":
        if form.is_valid():
            try:
                movement = execute_fn(form.cleaned_data)
            except (InsufficientStockError, BarServiceError) as exc:
                form.add_error(None, str(exc))
                toast_error_message = str(exc)
                if not htmx_partial:
                    status_code = 400
            else:
                success_message = (
                    f"{success_prefix} {movement.ingredient.name}."
                )
                if htmx_partial:
                    return render_oob_list_response(
                        request,
                        table_template=(
                            "bar/partials/stock_movement_table.html"
                        ),
                        target_id="stock-movement-list-region",
                        context_object_name="movement_list",
                        queryset=StockMovement.objects.select_related(
                            "ingredient",
                            "performed_by",
                            "order",
                        ),
                        paginate_by=20,
                        base_url=reverse("bar:stock-movement-list"),
                        toast_message=success_message,
                        extra_triggers={"stockChanged": True},
                    )
                messages.success(request, success_message)
                return redirect("bar:stock-movement-list")
        elif htmx_partial:
            toast_error_message = "Please correct the form errors."

    if htmx_partial:
        response = render(
            request,
            "bar/partials/drawer_form.html",
            {
                "form": form,
                "drawer_title": operation_title,
                "drawer_submit_label": operation_action,
                "form_action": request.path,
            },
            status=200,
        )
        if toast_error_message:
            return add_htmx_toast(
                response,
                level="error",
                message=toast_error_message,
            )
        return response

    return render(
        request,
        "bar/stock_operation_form.html",
        {
            "form": form,
            "operation_title": operation_title,
            "operation_action": operation_action,
        },
        status=status_code,
    )


@role_required(*MANAGER_ROLES)
def stock_in_view(request):
    """Receive stock and recalculate weighted average ingredient cost."""
    return _handle_stock_operation_request(
        request,
        form_class=StockInForm,
        operation_title="Stock In (Receipt)",
        operation_action="Record Stock In",
        execute_fn=lambda cleaned: record_stock_in(
            ingredient_id=cleaned["ingredient"].pk,
            quantity=cleaned["quantity"],
            unit_cost=cleaned["unit_cost"],
            performed_by=request.user,
            reason=cleaned.get("reason", ""),
            ip_address=get_client_ip(request),
        ),
        success_prefix="Stock in recorded for",
    )


@role_required(*MANAGER_ROLES)
def stock_writeoff_view(request):
    """Record spoilage or breakage write-off via atomic service."""
    return _handle_stock_operation_request(
        request,
        form_class=StockWriteoffForm,
        operation_title="Stock Write-off",
        operation_action="Record Write-off",
        execute_fn=lambda cleaned: record_writeoff(
            ingredient_id=cleaned["ingredient"].pk,
            quantity=cleaned["quantity"],
            reason=cleaned["reason"],
            performed_by=request.user,
            ip_address=get_client_ip(request),
        ),
        success_prefix="Write-off recorded for",
    )


@role_required(*MANAGER_ROLES)
def stock_adjustment_view(request):
    """Reconcile counted stock balance via atomic inventory adjustment."""
    return _handle_stock_operation_request(
        request,
        form_class=StockAdjustmentForm,
        operation_title="Inventory Adjustment",
        operation_action="Record Adjustment",
        execute_fn=lambda cleaned: record_adjustment(
            ingredient_id=cleaned["ingredient"].pk,
            actual_quantity=cleaned["actual_quantity"],
            reason=cleaned["reason"],
            performed_by=request.user,
            ip_address=get_client_ip(request),
        ),
        success_prefix="Adjustment recorded for",
    )
