from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views import generic
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib import messages

from bar.forms import (
    DrinkForm,
    BartenderStaffUpdateForm,
    BartenderCreationForm,
    DrinkSearchForm,
    BartenderSearchForm,
    CategorySearchForm,
    SupplierSearchForm,
    IngredientSearchForm,
)

from bar.models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinksCategory,
    Order,
)


@login_required
def index(request):
    num_drinks = Drink.objects.count()
    num_categories = DrinksCategory.objects.count()
    out_of_stock_ingredients = BarIngredient.objects.filter(
        stock_quantity=0
    ).count()
    active_orders = Order.objects.filter(is_paid=False).count()

    num_visits = request.session.get("num_visits", 0)
    request.session["num_visits"] = num_visits + 1

    context = {
        "num_drinks": num_drinks,
        "num_categories": num_categories,
        "active_orders": active_orders,
        "out_of_stock_ingredients": out_of_stock_ingredients,
        "num_visits": num_visits + 1,
    }

    return render(request, "bar/index.html", context=context)


class BaseSearchListView(LoginRequiredMixin, generic.ListView):
    paginate_by = 5
    search_form_class = None
    search_field = "name"

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
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
                lookup = f"{self.search_field}__icontains"
                return queryset.filter(
                    **{lookup: form.cleaned_data[self.search_field]}
                )
        return queryset


class DrinksCategoryListView(BaseSearchListView):
    model = DrinksCategory
    context_object_name = "category_list"
    template_name = "bar/category_list.html"
    search_form_class = CategorySearchForm


class CategoryCrudMixin(LoginRequiredMixin):
    model = DrinksCategory
    success_url = reverse_lazy("bar:category-list")


class CategoryFormMixin(CategoryCrudMixin):
    fields = "__all__"
    template_name = "bar/category_form.html"


class DrinksCategoryCreateView(CategoryFormMixin, generic.CreateView):
    pass


class DrinksCategoryUpdateView(CategoryFormMixin, generic.UpdateView):
    pass


class DrinksCategoryDeleteView(CategoryCrudMixin, generic.DeleteView):
    template_name = "bar/category_confirm_delete.html"


class BarSupplierListView(BaseSearchListView):
    model = BarSupplier
    context_object_name = "supplier_list"
    template_name = "bar/supplier_list.html"
    search_form_class = SupplierSearchForm


class SupplierCrudMixin(LoginRequiredMixin):
    model = BarSupplier
    success_url = reverse_lazy("bar:supplier-list")


class SupplierFormMixin(SupplierCrudMixin):
    fields = "__all__"
    template_name = "bar/supplier_form.html"


class BarSupplierCreateView(SupplierFormMixin, generic.CreateView):
    pass


class BarSupplierUpdateView(SupplierFormMixin, generic.UpdateView):
    pass


class BarSupplierDeleteView(SupplierCrudMixin, generic.DeleteView):
    template_name = "bar/supplier_confirm_delete.html"


class BarIngredientListView(BaseSearchListView):
    model = BarIngredient
    queryset = BarIngredient.objects.select_related("supplier")
    context_object_name = "ingredient_list"
    template_name = "bar/ingredient_list.html"
    search_form_class = IngredientSearchForm


class IngredientCrudMixin(LoginRequiredMixin):
    model = BarIngredient
    success_url = reverse_lazy("bar:ingredient-list")


class IngredientFormMixin(IngredientCrudMixin):
    fields = "__all__"
    template_name = "bar/ingredient_form.html"


class BarIngredientCreateView(IngredientFormMixin, generic.CreateView):
    pass


class BarIngredientUpdateView(IngredientFormMixin, generic.UpdateView):
    pass


class BarIngredientDeleteView(IngredientCrudMixin, generic.DeleteView):
    template_name = "bar/ingredient_confirm_delete.html"


class DrinksListView(BaseSearchListView):
    model = Drink
    queryset = Drink.objects.select_related("category")
    context_object_name = "drink_list"
    template_name = "bar/drink_list.html"
    search_form_class = DrinkSearchForm


class DrinkCrudMixin(LoginRequiredMixin):
    model = Drink
    success_url = reverse_lazy("bar:drink-list")


class DrinkFormMixin(DrinkCrudMixin):
    form_class = DrinkForm


class DrinkCreateView(DrinkFormMixin, generic.CreateView):
    pass


class DrinkUpdateView(DrinkFormMixin, generic.UpdateView):
    pass


class DrinkDeleteView(DrinkCrudMixin, generic.DeleteView):
    pass


class BartenderListView(BaseSearchListView):
    model = Bartender
    context_object_name = "bartender_list"
    template_name = "bar/bartender_list.html"
    search_field = "username"
    search_form_class = BartenderSearchForm


class BartenderCrudMixin(LoginRequiredMixin):
    model = Bartender
    success_url = reverse_lazy("bar:bartender-list")


class BartenderCreateView(BartenderCrudMixin, generic.CreateView):
    form_class = BartenderCreationForm


class BartenderStaffUpdateView(BartenderCrudMixin, generic.UpdateView):
    form_class = BartenderStaffUpdateForm


class BartenderDeleteView(BartenderCrudMixin, generic.DeleteView):
    pass


class OrderListView(LoginRequiredMixin, generic.ListView):
    model = Order
    context_object_name = "order_list"
    template_name = "bar/order_list.html"
    paginate_by = 5

    def get_queryset(self):
        return (
            Order.objects.prefetch_related("drinks")
            .select_related("bartender")
        )


class OrderDetailView(LoginRequiredMixin, generic.DetailView):
    model = Order
    template_name = "bar/order_detail.html"

    def get_queryset(self):
        return (
            Order.objects.prefetch_related("drinks__category")
            .select_related("bartender")
        )


class DrinkDetailView(LoginRequiredMixin, generic.DetailView):
    model = Drink
    template_name = "bar/drink_detail.html"

    def get_queryset(self):
        return (
            Drink.objects.select_related("category")
            .prefetch_related("ingredients__supplier")
        )


class BartenderDetailView(LoginRequiredMixin, generic.DetailView):
    model = Bartender
    template_name = "bar/bartender_detail.html"

    def get_queryset(self):
        queryset = Bartender.objects.prefetch_related("orders__drinks")
        return queryset


@login_required
@require_POST
def toggle_assign_order(request, pk):
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(), pk=pk
        )
        if order.bartender == request.user:
            order.bartender = None
            order.save(update_fields=["bartender"])
        elif order.bartender is None:
            order.bartender = request.user
            order.save(update_fields=["bartender"])
        else:
            messages.warning(
                request,
                "Order has been assigned by other Bartender"
            )
    return redirect("bar:order-detail", pk=pk)
