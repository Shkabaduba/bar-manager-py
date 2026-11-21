from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import generic

from bar.forms import (
    BartenderSearchForm,
    BartenderStaffUpdateForm,
    StaffCreateForm,
)
from bar.middleware import get_client_ip, parse_ip_address
from bar.models import AuditLog, Bartender, Order
from bar.permissions import (
    OWNER_ROLES,
    RoleRequiredMixin,
    StaffActionNotAllowedError,
    htmx_forbidden_response,
    sync_bartender_group,
    validate_can_change_role,
    validate_can_delete_bartender,
)
from bar.services.cache import schedule_analytics_cache_invalidation
from bar.views.mixins import BaseSearchListView


class BartenderListView(BaseSearchListView):
    model = Bartender
    context_object_name = "bartender_list"
    template_name = "bar/bartender_list.html"
    partial_template_name = "bar/partials/bartender_table.html"
    search_field = "username"
    search_form_class = BartenderSearchForm

    def get_queryset(self):
        queryset = super().get_queryset()
        role_param = self.request.GET.get("role", "").strip()
        if role_param in Bartender.Role.values:
            queryset = queryset.filter(role=role_param)
        return queryset


class BartenderDetailView(LoginRequiredMixin, generic.DetailView):
    model = Bartender
    template_name = "bar/bartender_detail.html"

    def get_queryset(self):
        return Bartender.objects.annotate(
            total_orders_count=Count("orders", distinct=True),
            paid_orders_count=Count(
                "orders",
                filter=Q(orders__status=Order.Status.PAID),
                distinct=True,
            ),
            total_revenue=Coalesce(
                Sum(
                    "orders__total_revenue_snapshot",
                    filter=Q(orders__status=Order.Status.PAID),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
        ).prefetch_related("orders__drinks")


class BartenderCrudMixin(RoleRequiredMixin):
    allowed_roles = OWNER_ROLES
    model = Bartender
    success_url = reverse_lazy("bar:bartender-list")


class BartenderCreateView(BartenderCrudMixin, generic.CreateView):
    form_class = StaffCreateForm
    template_name = "bar/bartender_form.html"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            sync_bartender_group(self.object)
            AuditLog.objects.create(
                actor=self.request.user,
                action="STAFF_CREATED",
                target_model="Bartender",
                target_id=str(self.object.pk),
                metadata={
                    "username": self.object.username,
                    "role": self.object.role,
                },
                ip_address=parse_ip_address(get_client_ip(self.request)),
            )
            schedule_analytics_cache_invalidation()
        return response


class BartenderStaffUpdateView(BartenderCrudMixin, generic.UpdateView):
    form_class = BartenderStaffUpdateForm
    template_name = "bar/bartender_form.html"

    def form_valid(self, form):
        new_role = form.cleaned_data["role"]
        with transaction.atomic():
            target = Bartender.objects.select_for_update().get(
                pk=self.object.pk
            )
            previous_role = target.role
            try:
                validate_can_change_role(self.request.user, target, new_role)
            except StaffActionNotAllowedError as exc:
                messages.error(self.request, str(exc))
                return htmx_forbidden_response(self.request, str(exc))

            response = super().form_valid(form)
            sync_bartender_group(self.object)
            if previous_role != new_role:
                AuditLog.objects.create(
                    actor=self.request.user,
                    action="STAFF_ROLE_UPDATED",
                    target_model="Bartender",
                    target_id=str(self.object.pk),
                    metadata={
                        "username": self.object.username,
                        "old_role": previous_role,
                        "new_role": new_role,
                    },
                    ip_address=parse_ip_address(get_client_ip(self.request)),
                )
            schedule_analytics_cache_invalidation()
        return response


class BartenderDeleteView(BartenderCrudMixin, generic.DeleteView):
    template_name = "bar/bartender_confirm_delete.html"

    def form_valid(self, form):
        target_pk = self.get_object().pk
        with transaction.atomic():
            target = Bartender.objects.select_for_update().get(pk=target_pk)
            try:
                validate_can_delete_bartender(self.request.user, target)
            except StaffActionNotAllowedError as exc:
                messages.error(self.request, str(exc))
                return htmx_forbidden_response(self.request, str(exc))

            deleted_id = str(target.pk)
            deleted_username = target.username
            deleted_role = target.role
            target.delete()
            AuditLog.objects.create(
                actor=self.request.user,
                action="STAFF_DELETED",
                target_model="Bartender",
                target_id=deleted_id,
                metadata={
                    "username": deleted_username,
                    "role": deleted_role,
                },
                ip_address=parse_ip_address(get_client_ip(self.request)),
            )
            schedule_analytics_cache_invalidation()
        return redirect(self.success_url)
