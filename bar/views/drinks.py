from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import generic

from bar.forms import (
    CategorySearchForm,
    DrinkIngredientFormSet,
    DrinkRecipeForm,
    DrinkSearchForm,
    DrinksCategoryForm,
)
from bar.models import BarIngredient, Drink, DrinksCategory
from bar.permissions import MANAGER_ROLES, RoleRequiredMixin, role_required
from bar.services.cache import schedule_analytics_cache_invalidation
from bar.services.costing import (
    RecipeLineInput,
    calculate_drink_costing,
    calculate_drinks_costing_map,
    calculate_recipe_costing,
)
from bar.views.mixins import (
    AnalyticsCacheInvalidationMixin,
    BaseSearchListView,
    HtmxDrawerFormMixin,
    ProtectedDeleteMixin,
)


class DrinksCategoryListView(BaseSearchListView):
    model = DrinksCategory
    context_object_name = "category_list"
    template_name = "bar/category_list.html"
    partial_template_name = "bar/partials/category_table.html"
    search_form_class = CategorySearchForm


class CategoryCrudMixin(RoleRequiredMixin):
    allowed_roles = MANAGER_ROLES
    model = DrinksCategory
    success_url = reverse_lazy("bar:category-list")


class CategoryFormMixin(
    HtmxDrawerFormMixin,
    AnalyticsCacheInvalidationMixin,
    CategoryCrudMixin,
):
    form_class = DrinksCategoryForm
    template_name = "bar/category_form.html"
    oob_table_template = "bar/partials/category_table.html"
    oob_target_id = "category-list-region"
    oob_context_object_name = "category_list"
    oob_event_name = "categoriesChanged"
    success_toast_message = _("Category saved.")


class DrinksCategoryCreateView(CategoryFormMixin, generic.CreateView):
    drawer_title = _("Create Category")


class DrinksCategoryUpdateView(CategoryFormMixin, generic.UpdateView):
    drawer_title = _("Update Category")


class DrinksCategoryDeleteView(
    ProtectedDeleteMixin,
    CategoryCrudMixin,
    generic.DeleteView,
):
    template_name = "bar/category_confirm_delete.html"
    oob_table_template = "bar/partials/category_table.html"
    oob_target_id = "category-list-region"
    oob_context_object_name = "category_list"
    oob_event_name = "categoriesChanged"


class DrinksListView(BaseSearchListView):
    model = Drink
    context_object_name = "drink_list"
    template_name = "bar/drink_list.html"
    partial_template_name = "bar/partials/drink_table.html"
    search_form_class = DrinkSearchForm

    def get_queryset(self):
        queryset = (
            Drink.objects.select_related("category")
            .prefetch_related("recipe_items__ingredient")
            .order_by("name")
        )
        form = self.search_form_class(self.request.GET)
        if form.is_valid():
            query = form.cleaned_data.get(self.search_field, "").strip()
            if query:
                queryset = queryset.filter(name__icontains=query)

        category_param = self.request.GET.get("category", "").strip()
        if category_param.isdigit():
            queryset = queryset.filter(category_id=int(category_param))

        active_param = self.request.GET.get("active", "").strip()
        if active_param == "1":
            queryset = queryset.filter(is_active=True)
        elif active_param == "0":
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super().get_context_data(object_list=object_list, **kwargs)
        drinks = list(context["drink_list"])
        costing_map = calculate_drinks_costing_map(drinks)
        for drink in drinks:
            drink.costing = costing_map[drink.pk]
        context["drink_list"] = drinks
        context["costing_map"] = costing_map
        context["categories"] = DrinksCategory.objects.all()
        context["selected_category"] = self.request.GET.get("category", "")
        return context


class DrinkDetailView(LoginRequiredMixin, generic.DetailView):
    model = Drink
    template_name = "bar/drink_detail.html"

    def get_queryset(self):
        return Drink.objects.select_related("category").prefetch_related(
            "ingredients__supplier",
            "recipe_items__ingredient__supplier",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["costing"] = calculate_drink_costing(self.object)
        return context


class DrinkCrudMixin(RoleRequiredMixin):
    allowed_roles = MANAGER_ROLES
    model = Drink
    success_url = reverse_lazy("bar:drink-list")


class DrinkRecipeMixin(DrinkCrudMixin):
    form_class = DrinkRecipeForm
    template_name = "bar/drink_form.html"
    queryset = Drink.objects.select_related("category").prefetch_related(
        "recipe_items__ingredient"
    )

    def get_recipe_formset(self, instance):
        if self.request.method == "POST":
            return DrinkIngredientFormSet(self.request.POST, instance=instance)
        return DrinkIngredientFormSet(instance=instance)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        target_drink = getattr(self, "object", None)
        if "recipe_formset" not in context:
            context["recipe_formset"] = self.get_recipe_formset(
                instance=target_drink or Drink()
            )
        context["costing_preview"] = (
            calculate_drink_costing(target_drink)
            if target_drink and target_drink.pk
            else None
        )
        context["ingredients_catalog"] = BarIngredient.objects.order_by(
            "name"
        )
        return context

    def _handle_recipe_post(self, request, *, target_object):
        self.object = target_object
        form = self.get_form()
        recipe_formset = self.get_recipe_formset(
            instance=target_object or Drink()
        )
        if form.is_valid() and recipe_formset.is_valid():
            with transaction.atomic():
                self.object = form.save()
                recipe_formset.instance = self.object
                recipe_formset.save()
                schedule_analytics_cache_invalidation()
            messages.success(
                request,
                f"Drink '{self.object.name}' saved.",
            )
            return redirect(self.get_success_url())
        return self.render_to_response(
            self.get_context_data(
                form=form,
                recipe_formset=recipe_formset,
            )
        )


class DrinkCreateView(DrinkRecipeMixin, generic.CreateView):
    def post(self, request, *args, **kwargs):
        return self._handle_recipe_post(request, target_object=None)


class DrinkUpdateView(DrinkRecipeMixin, generic.UpdateView):
    def post(self, request, *args, **kwargs):
        return self._handle_recipe_post(
            request,
            target_object=self.get_object(),
        )


class DrinkDeleteView(
    ProtectedDeleteMixin,
    DrinkCrudMixin,
    generic.DeleteView,
):
    template_name = "bar/drink_confirm_delete.html"


def _extract_preview_pairs(params) -> list[tuple[int, Decimal]]:
    raw_pairs: list[tuple[str, str]] = []
    if "recipe_items-TOTAL_FORMS" in params:
        total_forms = int(params.get("recipe_items-TOTAL_FORMS") or 0)
        for row_index in range(max(total_forms, 0)):
            delete_flag = str(
                params.get(f"recipe_items-{row_index}-DELETE", "")
            ).strip()
            if delete_flag in ("on", "true", "True", "1"):
                continue
            raw_ing_id = str(
                params.get(f"recipe_items-{row_index}-ingredient", "")
            ).strip()
            raw_amount = str(
                params.get(f"recipe_items-{row_index}-amount", "")
            ).strip()
            if raw_ing_id or raw_amount:
                raw_pairs.append((raw_ing_id, raw_amount))
    else:
        ingredient_ids = params.getlist("ingredient_id")
        amounts = params.getlist("amount")
        for raw_ing_id, raw_amount in zip(ingredient_ids, amounts):
            clean_ing_id = str(raw_ing_id).strip()
            clean_amount = str(raw_amount).strip()
            if clean_ing_id or clean_amount:
                raw_pairs.append((clean_ing_id, clean_amount))

    parsed_pairs: list[tuple[int, Decimal]] = []
    for raw_ing_id, raw_amount in raw_pairs:
        if not raw_ing_id or not raw_amount:
            continue
        ingredient_pk = int(raw_ing_id)
        amount_decimal = Decimal(raw_amount)
        parsed_pairs.append((ingredient_pk, amount_decimal))
    return parsed_pairs


@role_required(*MANAGER_ROLES)
def drink_costing_preview(request):
    """Render live HTMX costing simulation for the cocktail calculator."""
    params = request.POST if request.method == "POST" else request.GET
    costing = None
    preview_error = None

    try:
        raw_price = str(params.get("price", "")).strip()
        price_decimal = Decimal(raw_price) if raw_price else Decimal("0.00")

        raw_target = str(params.get("target_food_cost_pct", "")).strip()
        target_pct = (
            Decimal(raw_target) if raw_target else Decimal("25.00")
        )

        parsed_pairs = _extract_preview_pairs(params)
        ingredient_ids = sorted({ing_pk for ing_pk, _ in parsed_pairs})
        ingredients_map = BarIngredient.objects.in_bulk(ingredient_ids)
        recipe_lines: list[RecipeLineInput] = []
        for ingredient_pk, amount_decimal in parsed_pairs:
            ingredient = ingredients_map.get(ingredient_pk)
            if ingredient is None:
                raise ValueError(f"Ingredient #{ingredient_pk} was not found.")
            recipe_lines.append(
                RecipeLineInput(ingredient=ingredient, amount=amount_decimal)
            )
        costing = calculate_recipe_costing(
            recipe_lines,
            price=price_decimal,
            target_food_cost_pct=target_pct,
        )
    except (InvalidOperation, ValueError) as exc:
        preview_error = str(exc)

    return render(
        request,
        "bar/partials/drink_costing_preview.html",
        {
            "costing": costing,
            "preview_error": preview_error,
        },
    )
