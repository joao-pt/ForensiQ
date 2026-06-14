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
    EvidenceTypeRef,
    FieldOption,
    GuiaTransporte,
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


class ImmutableAdminMixin:
    """Política ÚNICA de read-only dos registos imutáveis no admin (ISO/IEC
    27037 — auditoria D49): sem edição nem eliminação; ``allow_add = False``
    desliga também a criação (AuditLog, que só nasce da instrumentação)."""

    allow_add = True

    def has_add_permission(self, request):
        return self.allow_add and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Evidence)
class EvidenceAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ('pk', 'type', 'occurrence', 'agent', 'timestamp_seizure', 'integrity_hash')
    list_filter = ('type', 'timestamp_seizure')
    search_fields = ('description', 'serial_number')
    raw_id_fields = ('occurrence', 'agent')
    readonly_fields = ('integrity_hash', 'created_at', 'updated_at')


@admin.register(ChainOfCustody)
class ChainOfCustodyAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ('pk', 'evidence', 'event_type', 'custodian_type', 'agent', 'timestamp')
    list_filter = ('event_type', 'custodian_type')
    # authority_nome pesquisável: "tudo o que a procuradora X validou" (hv4).
    search_fields = ('observations', 'location_name', 'storage_location', 'authority_nome')
    raw_id_fields = ('evidence', 'agent')
    readonly_fields = ('record_hash',)


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


@admin.register(GuiaTransporte)
class GuiaTransporteAdmin(admin.ModelAdmin):
    """Guia de transporte (remessa) — histórico NÃO-certificado, fora da cadeia de
    custódia. O PDF é re-gerado a pedido (não há ficheiro guardado). Apagável aqui
    quando deixar de ser útil; apagar a guia não toca no ledger (os eventos ficam)."""

    list_display = ('code', 'occurrence', 'created_at')
    search_fields = ('code', 'occurrence__code', 'occurrence__number')
    raw_id_fields = ('occurrence', 'events')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


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


@admin.register(EvidenceTypeRef)
class EvidenceTypeRefAdmin(admin.ModelAdmin):
    """Catálogo editável de tipos de evidência (ADR-0018).

    ``code`` é WRITE-ONCE (entra no registo e no hash): editável só na criação,
    só-leitura depois. Acrescentam-se códigos novos; nunca se renomeiam.
    """

    list_display = ('code', 'label', 'is_active', 'order')
    list_editable = ('label', 'is_active', 'order')
    list_filter = ('is_active',)
    search_fields = ('code', 'label')
    ordering = ('order', 'code')

    def get_readonly_fields(self, request, obj=None):
        return ('code',) if obj is not None else ()


@admin.register(AuditLog)
class AuditLogAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    """Registo de auditoria — read-only para todos os perfis (só nasce da
    instrumentação: ``allow_add = False`` desliga também a criação)."""

    allow_add = False

    list_display = ('timestamp', 'user', 'action', 'resource_type', 'resource_id', 'ip_address')
    list_filter = ('action', 'resource_type', 'timestamp')
    search_fields = ('user__username', 'ip_address', 'correlation_id')
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    ordering = ('-timestamp',)
