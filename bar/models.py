from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.conf import settings


class BarSupplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    phone = models.CharField(max_length=13)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class BarIngredient(models.Model):
    name = models.CharField(max_length=255, unique=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    supplier = models.ForeignKey(
        BarSupplier,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (in stock: {self.stock_quantity})"


class DrinksCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_alcohol = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories of drinks"

    def __str__(self):
        status = "Alcoholic" if self.is_alcohol else "Non-alcoholic"
        return f"{self.name} ({status})"


class Bartender(AbstractUser):
    staff_id = models.CharField(max_length=255, unique=True)

    class Meta:
        verbose_name = "bartender"
        verbose_name_plural = "bartenders"
        ordering = ["username"]

    def __str__(self):
        return f"{self.username} ({self.first_name} {self.last_name})"

    def get_absolute_url(self):
        return reverse("bar:bartender-detail", kwargs={"pk": self.pk})


class Drink(models.Model):
    name = models.CharField(max_length=255, unique=True)
    price = models.DecimalField(max_digits=7, decimal_places=2)
    volume_ml = models.PositiveIntegerField(default=250)
    category = models.ForeignKey(
        DrinksCategory,
        on_delete=models.CASCADE,
        related_name="drinks",
    )
    ingredients = models.ManyToManyField(
        BarIngredient,
        related_name="drinks",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.volume_ml}ml - ${self.price})"

    def get_absolute_url(self):
        return reverse("bar:drink-detail", kwargs={"pk": self.pk})


class Order(models.Model):
    table_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)
    bartender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    drinks = models.ManyToManyField(
        Drink,
        related_name="orders",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.id} (Table {self.table_number})"

    def get_absolute_url(self):
        return reverse("bar:order-detail", kwargs={"pk": self.pk})
