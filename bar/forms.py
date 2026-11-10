from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import Drink, BarIngredient, Bartender


class DrinkForm(forms.ModelForm):
    ingredients = forms.ModelMultipleChoiceField(
        queryset=BarIngredient.objects.all(),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Drink
        fields = "__all__"


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


class BartenderStaffUpdateForm(forms.ModelForm):
    class Meta:
        model = Bartender
        fields = ["staff_id"]

    def clean_staff_id(self):
        return validate_staff_id(self.cleaned_data["staff_id"])


def validate_staff_id(
    staff_id,
):
    if len(staff_id) < 8 or len(staff_id) > 15:
        raise ValidationError("Staff ID must be between 8 and 15 characters")

    return staff_id


class BartenderSearchForm(forms.Form):
    username = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(attrs={"placeholder": "Search by username"}
                               )
    )


class DrinkSearchForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(attrs={"placeholder": "Search by drink name"}
                               )
    )


class CategorySearchForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(attrs={"placeholder": "Search by name"})
    )


class SupplierSearchForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(
            attrs={"placeholder": "Search by supplier name"}
        )
    )


class IngredientSearchForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=False,
        label="",
        widget=forms.TextInput(
            attrs={"placeholder": "Search by ingredient name"}
        )
    )
