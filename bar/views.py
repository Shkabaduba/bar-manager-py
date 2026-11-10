from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views import generic
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib import messages

from .forms import (
    DrinkForm,
    BartenderStaffUpdateForm,
    BartenderCreationForm,
    DrinkSearchForm,
    BartenderSearchForm,
    CategorySearchForm,
)

from .models import (
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


class DrinksCategoryListView(LoginRequiredMixin, generic.ListView):
    model = DrinksCategory
    context_object_name = "category_list"
    template_name = "bar/category_list.html"
    paginate_by = 5

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        name = self.request.GET.get("name", "")
        context["search_form"] = CategorySearchForm(
            initial={"name": name}
        )
        return context

    def get_queryset(self):
        queryset = DrinksCategory.objects.all()
        form = CategorySearchForm(self.request.GET)
        if form.is_valid():
            return queryset.filter(
                name__icontains=form.cleaned_data["name"]
            )
        return queryset


class DrinksCategoryCreateView(LoginRequiredMixin, generic.CreateView):
    model = DrinksCategory
    fields = "__all__"
    template_name = "bar/category_form.html"
    success_url = reverse_lazy("bar:category-list")


class DrinksCategoryUpdateView(LoginRequiredMixin, generic.UpdateView):
    model = DrinksCategory
    fields = "__all__"
    template_name = "bar/category_form.html"
    success_url = reverse_lazy("bar:category-list")


class DrinksCategoryDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = DrinksCategory
    template_name = "bar/category_confirm_delete.html"
    success_url = reverse_lazy("bar:category-list")


class BarSupplierListView(LoginRequiredMixin, generic.ListView):
    model = BarSupplier
    context_object_name = "supplier_list"
    template_name = "bar/supplier_list.html"
    paginate_by = 5


class BarIngredientListView(LoginRequiredMixin, generic.ListView):
    model = BarIngredient
    context_object_name = "ingredient_list"
    template_name = "bar/ingredient_list.html"
    paginate_by = 5

    def get_queryset(self):
        queryset = BarIngredient.objects.select_related("supplier")
        return queryset


class DrinksListView(LoginRequiredMixin, generic.ListView):
    model = Drink
    context_object_name = "drink_list"
    template_name = "bar/drink_list.html"
    paginate_by = 5

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        name = self.request.GET.get("name", "")
        context["search_form"] = DrinkSearchForm(
            initial={"name": name}
        )
        return context

    def get_queryset(self):
        queryset = Drink.objects.select_related("category")
        form = DrinkSearchForm(self.request.GET)
        if form.is_valid():
            return queryset.filter(
                name__icontains=form.cleaned_data["name"]
            )
        return queryset


class DrinkCreateView(LoginRequiredMixin, generic.CreateView):
    model = Drink
    form_class = DrinkForm
    success_url = reverse_lazy("bar:drink-list")


class DrinkUpdateView(LoginRequiredMixin, generic.UpdateView):
    model = Drink
    form_class = DrinkForm
    success_url = reverse_lazy("bar:drink-list")


class DrinkDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = Drink
    success_url = reverse_lazy("bar:drink-list")


class BartenderListView(LoginRequiredMixin, generic.ListView):
    model = Bartender
    context_object_name = "bartender_list"
    template_name = "bar/bartender_list.html"
    paginate_by = 5

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(**kwargs)
        username = self.request.GET.get("username", "")
        context["search_form"] = BartenderSearchForm(
            initial={"username": username}
        )
        return context

    def get_queryset(self):
        queryset = Bartender.objects.all()
        form = BartenderSearchForm(self.request.GET)
        if form.is_valid():
            return queryset.filter(
                username__icontains=form.cleaned_data["username"]
            )
        return queryset


class BartenderCreateView(LoginRequiredMixin, generic.CreateView):
    model = Bartender
    form_class = BartenderCreationForm
    success_url = reverse_lazy("bar:bartender-list")


class BartenderStaffUpdateView(LoginRequiredMixin, generic.UpdateView):
    model = Bartender
    form_class = BartenderStaffUpdateForm
    success_url = reverse_lazy("bar:bartender-list")


class BartenderDeleteView(LoginRequiredMixin, generic.DeleteView):
    model = Bartender
    success_url = reverse_lazy("bar:bartender-list")


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
            Order.objects.prefetch_related("drinks")
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
