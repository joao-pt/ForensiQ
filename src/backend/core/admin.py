"""ForensiQ — Registo de modelos no Django Admin."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    Evidence,
    Occurrence,
    PoliticaCriminalPrioridade,
    PrioridadeCrimeTipo,
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
    list_display = (
        'number',
        'crime_type',
        'priority',
        'priority_source',
        'date_time',
        'agent',
        'created_at',
    )
    list_filter = ('priority', 'priority_source', 'date_time')
    search_fields = ('number', 'description', 'address', 'crime_type__descritivo')
    raw_id_fields = ('agent', 'crime_type')


# ---------------------------------------------------------------------------
# Taxonomia de crimes + Política Criminal (dados de referência — ADR-0014).
# Editáveis no admin (não são prova; sem invariantes de imutabilidade).
# ---------------------------------------------------------------------------


@admin.register(CrimeCategoria)
class CrimeCategoriaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nome')
    search_fields = ('codigo', 'nome')
    ordering = ('codigo',)


@admin.register(CrimeSubcategoria)
class CrimeSubcategoriaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nome', 'categoria')
    list_filter = ('categoria',)
    search_fields = ('codigo', 'nome')
    ordering = ('codigo',)


@admin.register(CrimeTipo)
class CrimeTipoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descritivo', 'subcategoria', 'is_active')
    list_filter = ('is_active', 'subcategoria__categoria')
    search_fields = ('codigo', 'descritivo')
    ordering = ('codigo',)


class PrioridadeCrimeTipoInline(admin.TabularInline):
    model = PrioridadeCrimeTipo
    extra = 0
    raw_id_fields = ('crime_tipo',)


@admin.register(PoliticaCriminalPrioridade)
class PoliticaCriminalPrioridadeAdmin(admin.ModelAdmin):
    list_display = ('lei', 'biennium', 'is_active', 'vigente_desde', 'vigente_ate')
    list_filter = ('is_active',)
    search_fields = ('lei', 'biennium')
    inlines = [PrioridadeCrimeTipoInline]


@admin.register(PrioridadeCrimeTipo)
class PrioridadeCrimeTipoAdmin(admin.ModelAdmin):
    list_display = ('politica', 'crime_tipo', 'eixo')
    list_filter = ('eixo', 'politica')
    raw_id_fields = ('crime_tipo',)


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


@admin.register(ChainOfCustody)
class ChainOfCustodyAdmin(admin.ModelAdmin):
    list_display = ('pk', 'evidence', 'event_type', 'custodian_type', 'agent', 'timestamp')
    list_filter = ('event_type', 'custodian_type')
    search_fields = ('observations', 'location_name', 'storage_location')
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
