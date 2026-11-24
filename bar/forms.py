from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from bar.models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
    StockMovement,
    staff_id_validator,
)


def _clean_required_text(raw_text: str, field_label: str) -> str:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValidationError(f"{field_label} cannot be blank.")
    return cleaned


class BartenderCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Bartender
        fields = UserCreationForm.Meta.fields + (
            "staff_id",
            "first_name",
            "last_name",
        )

    def clean_staff_id(self):
        return validate_staff_id(self.cleaned_data["staff_id"])


class StaffCreateForm(BartenderCreationForm):
    class Meta(BartenderCreationForm.Meta):
        fields = BartenderCreationForm.Meta.fields + ("role",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].required = False
        self.fields["role"].initial = Bartender.Role.BARTENDER

    def clean_role(self):
        return self.cleaned_data.get("role") or Bartender.Role.BARTENDER


class BartenderStaffUpdateForm(forms.ModelForm):
    class Meta:
        model = Bartender
        fields = ["staff_id", "role"]

    def clean_staff_id(self):
        return validate_staff_id(self.cleaned_data["staff_id"])


def validate_staff_id(staff_id):
    staff_id_validator(staff_id)
    return staff_id


class BaseNameSearchForm(forms.Form):
    placeholder = "Search by name"

    name = forms.CharField(
        max_length=255,
        required=False,
        label="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs["placeholder"] = self.placeholder


class BartenderSearchForm(forms.Form):
    username = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(
            attrs={"placeholder": "Search by username"}
        ),
    )


class DrinkSearchForm(BaseNameSearchForm):
    placeholder = "Search by drink name"


class CategorySearchForm(BaseNameSearchForm):
    placeholder = "Search by category name"


class SupplierSearchForm(BaseNameSearchForm):
    placeholder = "Search by supplier name"


class IngredientSearchForm(BaseNameSearchForm):
    placeholder = "Search by ingredient name"


class DrinksCategoryForm(forms.ModelForm):
    class Meta:
        model = DrinksCategory
        fields = ["name", "is_alcohol"]


class BarSupplierForm(forms.ModelForm):
    class Meta:
        model = BarSupplier
        fields = ["name", "phone", "email", "notes", "is_active"]


class BaseBarIngredientForm(forms.ModelForm):
    class Meta:
        model = BarIngredient
        fields = ["name", "unit", "min_stock_threshold", "supplier"]

    def clean_min_stock_threshold(self):
        threshold = self.cleaned_data["min_stock_threshold"]
        if threshold < Decimal("0"):
            raise ValidationError(
                "Minimum stock threshold cannot be negative."
            )
        return threshold


class BarIngredientCreateForm(BaseBarIngredientForm):
    pass


class BarIngredientUpdateForm(BaseBarIngredientForm):
    pass


class DrinkRecipeForm(forms.ModelForm):
    class Meta:
        model = Drink
        fields = [
            "name",
            "category",
            "price",
            "volume_ml",
            "target_food_cost_pct",
            "is_active",
            "description",
        ]

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price <= Decimal("0"):
            raise ValidationError("Price must be greater than zero.")
        return price

    def clean_target_food_cost_pct(self):
        pct = self.cleaned_data["target_food_cost_pct"]
        if pct <= Decimal("0") or pct > Decimal("100"):
            raise ValidationError(
                "Target food cost must be between 0.01 and 100.00."
            )
        return pct


class DrinkIngredientLineForm(forms.ModelForm):
    class Meta:
        model = DrinkIngredient
        fields = ["ingredient", "amount"]

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= Decimal("0"):
            raise ValidationError("Amount must be greater than zero.")
        return amount


class BaseDrinkIngredientFormSet(BaseInlineFormSet):
    def clean(self):
        seen_ingredients: set[int] = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            ingredient = form.cleaned_data.get("ingredient")
            if ingredient is None:
                continue
            if ingredient.pk in seen_ingredients:
                raise ValidationError(
                    "Each ingredient can appear only once in a recipe."
                )
            seen_ingredients.add(ingredient.pk)
        super().clean()


DrinkIngredientFormSet = inlineformset_factory(
    Drink,
    DrinkIngredient,
    form=DrinkIngredientLineForm,
    formset=BaseDrinkIngredientFormSet,
    extra=1,
    can_delete=True,
)


class StockInForm(forms.Form):
    ingredient = forms.ModelChoiceField(
        queryset=BarIngredient.objects.select_related("supplier").order_by(
            "name"
        ),
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000.00"),
    )
    unit_cost = forms.DecimalField(
        max_digits=10,
        decimal_places=4,
        min_value=Decimal("0.0000"),
        max_value=Decimal("1000000.00"),
    )
    reason = forms.CharField(max_length=255, required=False)


class StockWriteoffForm(forms.Form):
    ingredient = forms.ModelChoiceField(
        queryset=BarIngredient.objects.select_related("supplier").order_by(
            "name"
        ),
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("1000000.00"),
    )
    reason = forms.CharField(max_length=255, required=True)

    def clean_reason(self):
        return _clean_required_text(self.cleaned_data["reason"], "Reason")


class StockAdjustmentForm(forms.Form):
    ingredient = forms.ModelChoiceField(
        queryset=BarIngredient.objects.select_related("supplier").order_by(
            "name"
        ),
    )
    actual_quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        max_value=Decimal("1000000.00"),
    )
    reason = forms.CharField(max_length=255, required=True)

    def clean_reason(self):
        return _clean_required_text(self.cleaned_data["reason"], "Reason")


class OrderCreateForm(forms.Form):
    table_number = forms.IntegerField(min_value=1, max_value=999)
    assign_to_me = forms.BooleanField(required=False, initial=True)


class OrderForceCloseForm(forms.Form):
    override_reason = forms.CharField(
        min_length=3,
        max_length=255,
        required=True,
    )
    expected_version = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput,
    )

    def clean_override_reason(self):
        cleaned = _clean_required_text(
            self.cleaned_data["override_reason"],
            "Override reason",
        )
        if len(cleaned) < 3:
            raise ValidationError(
                "Override reason must be at least 3 characters."
            )
        return cleaned


class StockMovementFilterForm(forms.Form):
    movement_type = forms.ChoiceField(
        choices=[("", "All types"), *StockMovement.MovementType.choices],
        required=False,
    )
    ingredient = forms.ModelChoiceField(
        queryset=BarIngredient.objects.order_by("name"),
        required=False,
        empty_label="All ingredients",
    )


class AuditLogFilterForm(forms.Form):
    action = forms.CharField(max_length=64, required=False)
    actor = forms.ModelChoiceField(
        queryset=Bartender.objects.order_by("username"),
        required=False,
        empty_label="All users",
    )
