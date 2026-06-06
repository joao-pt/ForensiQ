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
    EvidenceFieldDef,
    FieldOption,
    Institution,
    InstitutionMembership,
    Occurrence,
    PoliticaCriminalPrioridade,
    Portador,
    PrioridadeCrimeTipo,
    ProvaEmTransito,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username',
        'email',
        'get_full_name',
        'profile',
        'clearance',
        'badge_number',
        'is_active',
    )
    list_filter = ('profile', 'clearance', 'is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'badge_number')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('ForensiQ', {'fields': ('profile', 'clearance', 'badge_number', 'phone')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('ForensiQ', {'fields': ('profile', 'clearance', 'badge_number')}),
    )


class InstitutionMembershipInline(admin.TabularInline):
    model = InstitutionMembership
    extra = 0
    raw_id_fields = ('user',)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'sigla', 'is_active')
    list_filter = ('type', 'is_active')
    search_fields = ('name', 'sigla')
    ordering = ('name',)
    inlines = [InstitutionMembershipInline]


@admin.register(InstitutionMembership)
class InstitutionMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'institution', 'is_active', 'joined_at')
    list_filter = ('is_active', 'institution__type')
    search_fields = ('user__username', 'institution__name', 'institution__sigla')
    raw_id_fields = ('user', 'institution')


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


@admin.register(Portador)
class PortadorAdmin(admin.ModelAdmin):
    """Portadores (ADR-0016 v2) — dado de referência mutável, gerido no admin.

    O Portador NÃO concede acesso (é metadado); o que entra no ledger é o
    *snapshot* no momento do encaminhamento, imutável.
    """

    list_display = ('matricula', 'apelido', 'nome', 'posto', 'is_active', 'user')
    list_filter = ('is_active', 'posto')
    search_fields = ('matricula', 'nome', 'apelido', 'posto')
    raw_id_fields = ('user',)
    ordering = ('apelido', 'nome')


@admin.register(ProvaEmTransito)
class ProvaEmTransitoAdmin(admin.ModelAdmin):
    """Caixa "prova a chegar" (ADR-0016 v2) — leitura/reconhecimento manual."""

    list_display = ('pk', 'evidence', 'destino_institution', 'created_at', 'acknowledged_at')
    list_filter = ('destino_institution', 'acknowledged_at')
    search_fields = ('evidence__code',)
    raw_id_fields = ('evidence', 'encaminhamento_event', 'destino_institution')
    readonly_fields = ('encaminhamento_event', 'created_at')


# ---------------------------------------------------------------------------
# Configuração de campos por tipo de evidência (dados de referência editáveis)
# ---------------------------------------------------------------------------


class FieldOptionInline(admin.TabularInline):
    model = FieldOption
    extra = 1


@admin.register(EvidenceFieldDef)
class EvidenceFieldDefAdmin(admin.ModelAdmin):
    list_display = (
        'evidence_type',
        'key',
        'label',
        'input',
        'required',
        'validator',
        'sensitive',
        'order',
        'is_active',
    )
    list_filter = ('evidence_type', 'input', 'required', 'sensitive', 'is_active')
    search_fields = ('key', 'label', 'evidence_type')
    ordering = ('evidence_type', 'order', 'key')
    inlines = [FieldOptionInline]


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
