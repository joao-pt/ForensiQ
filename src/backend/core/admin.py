"""ForensiQ — Registo de modelos no Django Admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AuditLog,
    ChainOfCustody,
    DigitalDevice,
    Evidence,
    Occurrence,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'get_full_name', 'profile', 'badge_number', 'is_active')
    list_filter = ('profile', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'badge_number')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('ForensiQ', {'fields': ('profile', 'badge_number', 'phone')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('ForensiQ', {'fields': ('profile', 'badge_number')}),
    )


@admin.register(Occurrence)
class OccurrenceAdmin(admin.ModelAdmin):
    list_display = ('number', 'description', 'date_time', 'agent', 'created_at')
    list_filter = ('date_time',)
    search_fields = ('number', 'description', 'address')
    raw_id_fields = ('agent',)


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ('pk', 'type', 'occurrence', 'agent', 'timestamp_seizure', 'integrity_hash')
    list_filter = ('type', 'timestamp_seizure')
    search_fields = ('description', 'serial_number')
    raw_id_fields = ('occurrence', 'agent')
    readonly_fields = ('integrity_hash', 'created_at', 'updated_at')

    def has_change_permission(self, request, obj=None):
        """Evidências são imutáveis após registo (ISO/IEC 27037) — sem edição."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Evidências são imutáveis — sem eliminação."""
        return False


@admin.register(DigitalDevice)
class DigitalDeviceAdmin(admin.ModelAdmin):
    list_display = ('pk', 'type', 'brand', 'commercial_name', 'model', 'condition', 'imei', 'evidence')
    list_filter = ('type', 'condition')
    search_fields = ('brand', 'commercial_name', 'model', 'imei', 'serial_number')
    raw_id_fields = ('evidence',)


@admin.register(ChainOfCustody)
class ChainOfCustodyAdmin(admin.ModelAdmin):
    list_display = ('pk', 'evidence', 'previous_state', 'new_state', 'agent', 'timestamp')
    list_filter = ('new_state',)
    search_fields = ('observations',)
    raw_id_fields = ('evidence', 'agent')
    readonly_fields = ('record_hash',)

    def has_change_permission(self, request, obj=None):
        """Registos de custódia são imutáveis — sem edição."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Registos de custódia são imutáveis — sem eliminação."""
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Registo de auditoria — read-only para todos os perfis."""
    list_display = ('timestamp', 'user', 'action', 'resource_type', 'resource_id', 'ip_address')
    list_filter = ('action', 'resource_type', 'timestamp')
    search_fields = ('user__username', 'ip_address', 'correlation_id')
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    ordering = ('-timestamp',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
