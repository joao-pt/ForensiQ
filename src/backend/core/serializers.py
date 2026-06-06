"""
ForensiQ — Serializers para a API REST.

Cada entidade do modelo de dados tem um serializer dedicado.
Campos sensíveis (hashes, timestamps automáticos) são read-only.
Validações de ownership bloqueiam IDOR a nível de payload (Wave 2c).
"""

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from . import access
from .models import (
    AuditLog,
    ChainOfCustody,
    CrimeCategoria,
    CrimeSubcategoria,
    CrimeTipo,
    CustodianType,
    EventType,
    Evidence,
    Institution,
    Occurrence,
    derive_legal_state,
)
from .utils import get_user_display_name, sort_custody_chain
from .validators import validate_gps_coherence

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers partilhados
# ---------------------------------------------------------------------------


def _user_can_access_occurrence(user, occurrence) -> bool:
    """Acesso à OCORRÊNCIA para operar sobre o dossier (IDOR a nível de payload).

    Need-to-know derivado do ledger (ADR-0017) — fonte única em
    :mod:`core.access`: titular, credencial nacional, ou autoridade do caso.
    """
    return access.can_access_occurrence(user, occurrence)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class UserSerializer(serializers.ModelSerializer):
    """Serializer público (listagem) — sem ``badge_number`` nem PII.

    Usado em selects de frontend (ex. dropdown de custódia). Não expõe
    email, telefone ou crachá — apenas identidade operacional mínima.
    """

    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        """Nome completo, com fallback para username."""
        return get_user_display_name(obj)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'full_name',
            'first_name',
            'last_name',
            'profile',
        ]
        read_only_fields = ['id']


class UserDetailSerializer(serializers.ModelSerializer):
    """Serializer privado — apenas para o utilizador autenticado (/me/)."""

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'first_name',
            'last_name',
            'profile',
            'badge_number',
            'phone',
        ]
        read_only_fields = ['id', 'profile', 'badge_number']


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer para criação de utilizador (inclui password)."""

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'password',
            'first_name',
            'last_name',
            'profile',
            'badge_number',
            'phone',
        ]
        read_only_fields = ['id']

    def validate_password(self, value):
        """Corre AUTH_PASSWORD_VALIDATORS do Django contra a palavra-passe."""
        try:
            password_validation.validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        # Defesa em profundidade (CWE-521): repete validate_password contra
        # os AUTH_PASSWORD_VALIDATORS antes de gravar o hash, já com o user
        # construído (permite ao UserAttributeSimilarityValidator comparar
        # a senha com username/email/first_name).
        password_validation.validate_password(password, user=user)
        user.set_password(password)
        user.save()
        return user


# ---------------------------------------------------------------------------
# Occurrence
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Institution (ponto de controlo) — criação manual
# ---------------------------------------------------------------------------


class InstitutionSerializer(serializers.ModelSerializer):
    """Criação/edição manual de instituição (ponto de controlo fixo).

    **Obrigatórios: nome, tipo, morada e GPS.** A georreferência é exigida porque
    é COPIADA para o evento na receção (GPS-só-no-terreno). A obrigatoriedade vive
    AQUI — não no ``clean()`` do modelo — para não invalidar instituições já
    semeadas sem morada/GPS. O ``create``/``update`` corre ``full_clean()`` para
    aplicar a coerência e a quantização GPS a 7 casas definidas no modelo.
    """

    class Meta:
        model = Institution
        fields = [
            'id',
            'name',
            'type',
            'sigla',
            'address',
            'gps_lat',
            'gps_lng',
            'email',
            'phone',
            'is_active',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'address': {'required': True, 'allow_blank': False},
            'gps_lat': {'required': True, 'allow_null': False},
            'gps_lng': {'required': True, 'allow_null': False},
        }

    def create(self, validated_data):
        instance = Institution(**validated_data)
        instance.full_clean()  # coerência + quantização GPS + validadores de range
        instance.save()
        return instance

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.full_clean()
        instance.save()
        return instance


class OccurrenceSerializer(serializers.ModelSerializer):
    """Serializer para ocorrências policiais.

    ``crime_type`` (Tabela de Crimes Registados, N3) é obrigatório na criação.
    ``priority``/``priority_source`` são **derivados** pelo modelo (ADR-0014) e
    read-only. O sinal de override manual entra via ``elevar_prioridade`` (só
    eleva NORMAL→PRIORITÁRIA; a lei prevalece como fonte).
    """

    agent_name = serializers.SerializerMethodField()
    crime_type = serializers.PrimaryKeyRelatedField(
        queryset=CrimeTipo.objects.filter(is_active=True),
    )
    crime_type_label = serializers.SerializerMethodField()
    elevar_prioridade = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text='Se verdadeiro, eleva manualmente a prioridade para PRIORITÁRIA.',
    )

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return get_user_display_name(obj.agent)

    def get_crime_type_label(self, obj):
        """Rótulo legível do tipo de crime (ex.: '40 — Roubo na via pública')."""
        ct = obj.crime_type
        return f'{ct.codigo} — {ct.descritivo}' if ct else None

    def create(self, validated_data):
        # O override manual sinaliza-se pondo priority_source=MANUAL antes do
        # save; o modelo (_aplicar_prioridade) finaliza a derivação.
        if validated_data.pop('elevar_prioridade', False):
            validated_data['priority_source'] = Occurrence.PrioritySource.MANUAL
        return super().create(validated_data)

    class Meta:
        model = Occurrence
        fields = [
            'id',
            'code',
            'number',
            'description',
            'date_time',
            'gps_lat',
            'gps_lng',
            'address',
            'crime_type',
            'crime_type_label',
            'priority',
            'priority_source',
            'elevar_prioridade',
            'agent',
            'agent_name',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'code',
            'agent',
            'priority',
            'priority_source',
            'crime_type_label',
            'created_at',
            'updated_at',
        ]


# ---------------------------------------------------------------------------
# Taxonomia de crimes (read-only) — alimenta o seletor em cascata N1>N2>N3
# ---------------------------------------------------------------------------


class CrimeCategoriaSerializer(serializers.ModelSerializer):
    """Nível 1 (categoria) — para o primeiro select da cascata."""

    class Meta:
        model = CrimeCategoria
        fields = ['id', 'codigo', 'nome']


class CrimeSubcategoriaSerializer(serializers.ModelSerializer):
    """Nível 2 (subcategoria) — filtrada por categoria."""

    class Meta:
        model = CrimeSubcategoria
        fields = ['id', 'codigo', 'nome']


class CrimeTipoSimpleSerializer(serializers.ModelSerializer):
    """Nível 3 (tipo) com a flag de prioridade derivada da lei vigente.

    ``is_prioritaria`` é True se o tipo está no eixo INVESTIGAÇÃO (Art. 5.º)
    da versão activa da Política Criminal — o que a vista de ocorrência usa
    para a pré-visualização do badge P1. A vista pré-calcula o conjunto de
    ids prioritários (``context['prioritaria_ids']``) para evitar N+1.
    """

    is_prioritaria = serializers.SerializerMethodField()

    class Meta:
        model = CrimeTipo
        fields = ['id', 'codigo', 'descritivo', 'is_prioritaria']

    def get_is_prioritaria(self, obj):
        return obj.id in (self.context.get('prioritaria_ids') or set())


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceSerializer(serializers.ModelSerializer):
    """
    Serializer para evidências.

    O campo ``integrity_hash`` é calculado automaticamente pelo modelo e
    nunca pode ser definido pelo cliente. Evidências são imutáveis após
    criação (ISO/IEC 27037).

    Campos específicos do tipo (IMEI, VIN, IMSI, MAC, ...) entram via
    ``type_specific_data``; os validadores de formato correm no serializer
    e no ``Model.clean()`` (defesa em profundidade).

    Os campos ``external_lookup_*`` são **read-only** — só o endpoint de
    lookup (a integrar via Wave 2d) pode materializar o snapshot no
    registo.
    """

    agent_name = serializers.SerializerMethodField()
    parent_evidence = serializers.PrimaryKeyRelatedField(
        queryset=Evidence.objects.all(),
        allow_null=True,
        required=False,
    )
    parent_evidence_label = serializers.SerializerMethodField()
    occurrence_number = serializers.CharField(
        source='occurrence.number',
        read_only=True,
    )
    occurrence_code = serializers.CharField(
        source='occurrence.code',
        read_only=True,
    )
    type_specific_data = serializers.JSONField(required=False)
    sub_components = serializers.SerializerMethodField()
    current_state = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return get_user_display_name(obj.agent)

    def get_parent_evidence_label(self, obj):
        """Rótulo amigável do pai (ex.: 'ITM-2026-00001 · Telemóvel — S23'),
        para a UI não mostrar #id puro. Nulo se não tiver pai.
        """
        parent = obj.parent_evidence
        if parent is None:
            return None
        type_label = parent.get_type_display()
        desc = (parent.description or '').strip()
        short_desc = desc[:50] + ('…' if len(desc) > 50 else '')
        parts = [parent.code, type_label]
        if short_desc:
            parts.append(short_desc)
        return ' · '.join(p for p in parts if p)

    def get_sub_components(self, obj):
        """Lista compacta dos sub-componentes directos (sem recursão profunda).

        ISO/IEC 27037: um SIM ou cartão de memória dentro de um telemóvel
        deve acompanhar o pai na cadeia de custódia — aqui expomos essa
        relação para o frontend renderizar a árvore no detalhe do item.
        """
        children = obj.sub_components.select_related('agent').order_by('id')
        return [
            {
                'id': c.id,
                'code': c.code,
                'type': c.type,
                'description': c.description,
                'serial_number': c.serial_number,
                'timestamp_seizure': c.timestamp_seizure,
                'integrity_hash': c.integrity_hash,
            }
            for c in children
        ]

    def get_current_state(self, obj):
        """Estado legal DERIVADO da cadeia de custódia (ADR-0015 §6).

        Calcula :func:`derive_legal_state` sobre a sequência completa de
        eventos da evidência. Devolve ``None`` se a evidência ainda não tem
        nenhum registo de custódia.

        Nota: usa a relação ``custody_chain`` (prefetchada no caminho normal
        das listagens via ``Meta.ordering = ['evidence', 'sequence']``); o
        estado é uma função pura do log, nunca uma coluna gravada.
        """
        eventos = list(obj.custody_chain.all())
        if not eventos:
            return None
        eventos = sort_custody_chain(eventos)
        return derive_legal_state(eventos)

    class Meta:
        model = Evidence
        fields = [
            'id',
            'code',
            'occurrence',
            'occurrence_number',
            'occurrence_code',
            'type',
            'parent_evidence',
            'parent_evidence_label',
            'description',
            'photo',
            'gps_lat',
            'gps_lng',
            'timestamp_seizure',
            'serial_number',
            'agent',
            'agent_name',
            'integrity_hash',
            'type_specific_data',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'sub_components',
            'current_state',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'code',
            'agent',
            'timestamp_seizure',
            'integrity_hash',
            'external_lookup_snapshot',
            'external_lookup_source',
            'external_lookup_at',
            'sub_components',
            'current_state',
            'occurrence_number',
            'occurrence_code',
            'parent_evidence_label',
            'created_at',
            'updated_at',
        ]

    def validate_occurrence(self, occurrence):
        """AGENT só pode criar evidências em ocorrências próprias."""
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return occurrence
        if not _user_can_access_occurrence(request.user, occurrence):
            raise serializers.ValidationError(
                'Não pode criar evidências em ocorrências de outros agentes.'
            )
        return occurrence

    def validate(self, attrs):
        """Validação cruzada: tipo × type_specific_data × parent."""
        attrs = super().validate(attrs)
        tsd = attrs.get('type_specific_data')
        if tsd is None and self.instance is not None:
            tsd = self.instance.type_specific_data or {}
        tsd = tsd or {}
        if not isinstance(tsd, dict):
            raise serializers.ValidationError(
                {'type_specific_data': 'Deve ser um objecto JSON (dicionário).'}
            )

        etype = attrs.get('type') or (self.instance and self.instance.type)

        # --- Validadores por tipo: fonte ÚNICA partilhada com Model.clean
        #     (evidence_field_config.validate_type_specific_data). Cobre TODOS os
        #     tipos/campos com validador (imei_2, GPS_TRACKER, IOT_DEVICE,
        #     VEHICLE_COMPONENT…) e acumula um erro por campo — sem a escada
        #     if/elif que tinha drift e sobrepunha iccid sobre imsi. Defesa em
        #     profundidade: o Model.clean() reaplica os mesmos validadores.
        from core import evidence_field_config

        problems = evidence_field_config.validate_type_specific_data(etype, tsd)
        if problems:
            raise serializers.ValidationError(
                {'type_specific_data': ' | '.join(problems)}
            )

        # --- Parent evidence: tem de partilhar ocorrência.
        parent = attrs.get('parent_evidence')
        if parent is not None:
            occ = attrs.get('occurrence') or (self.instance and self.instance.occurrence)
            occ_id = occ.id if occ is not None else None
            if parent.occurrence_id != occ_id:
                raise serializers.ValidationError(
                    {'parent_evidence': ('Sub-componente tem de pertencer à mesma ocorrência.')}
                )

        return attrs


# ---------------------------------------------------------------------------
# ChainOfCustody
# ---------------------------------------------------------------------------


class ChainOfCustodySerializer(serializers.ModelSerializer):
    """
    Serializer para registos do ledger de eventos da custódia (ADR-0015).

    Append-only: apenas criação é permitida.
    O ``record_hash`` é calculado automaticamente pelo modelo.
    O ``sequence`` e o ``timestamp`` são determinados pelo servidor —
    nunca pelo cliente.

    Input do agente: ``event_type`` (obrigatório), ``custodian_type``,
    ``location_name``, ``storage_location`` e GPS (``gps_lat``/``gps_lng``/
    ``gps_accuracy_m``, ADR-0013). O ``legal_state`` (estado legal derivado)
    é read-only — função pura do log, nunca uma coluna que se contradiga.

    Valida ownership: só AGENT dono da ocorrência, EXPERT ou staff podem
    criar registos (fecha IDOR identificado na auditoria 2026-04-19).
    """

    agent_name = serializers.SerializerMethodField()
    evidence_code = serializers.CharField(source='evidence.code', read_only=True)
    legal_state = serializers.SerializerMethodField()

    def get_agent_name(self, obj):
        """Retorna nome completo do agente, com fallback para username."""
        return get_user_display_name(obj.agent)

    def get_legal_state(self, obj):
        """Estado legal derivado da sequência completa de eventos da evidência."""
        eventos = list(obj.evidence.custody_chain.all())
        eventos = sort_custody_chain(eventos)
        return derive_legal_state(eventos)

    class Meta:
        model = ChainOfCustody
        fields = [
            'id',
            'code',
            'evidence',
            'evidence_code',
            'sequence',
            'event_type',
            'custodian_type',
            'custodian_institution',
            'custodian_user',
            'location_name',
            'storage_location',
            'gps_lat',
            'gps_lng',
            'gps_accuracy_m',
            'legal_state',
            'agent',
            'agent_name',
            'timestamp',
            'observations',
            'sealed',
            'seal_condition_on_receipt',
            'new_seal_number',
            'relinquished_by',
            'bearer',
            'bearer_matricula',
            'bearer_nome',
            'bearer_apelido',
            'bearer_posto',
            'record_hash',
            'hash_version',
        ]
        read_only_fields = [
            'id',
            'code',
            'evidence_code',
            'agent',
            'sequence',
            'legal_state',
            'timestamp',
            # Snapshot do portador + versão: derivados/gravados pelo modelo no
            # save() (ADR-0016 v2) — só o FK ``bearer`` é input do cliente.
            'bearer_matricula',
            'bearer_nome',
            'bearer_apelido',
            'bearer_posto',
            'record_hash',
            'hash_version',
        ]

    def validate(self, attrs):
        """Coerência GPS + gate de ESCRITA item-level (ADR-0017 §5)."""
        lat = attrs.get('gps_lat')
        lng = attrs.get('gps_lng')
        try:
            validate_gps_coherence(lat, lng)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc
        # Gate de ESCRITA — FALHA FECHADA: se o serializer for instanciado sem
        # request/utilizador autenticado não conseguimos autorizar, logo NEGA-SE
        # (antes ignorava-se a verificação quando faltava o contexto — fail-open).
        # Todos os chamadores reais passam contexto: o ViewSet via get_serializer e
        # a view de intake define request.user + context={'request': request}.
        evidence = attrs.get('evidence')
        if evidence is not None:
            request = self.context.get('request')
            user = getattr(request, 'user', None)
            if user is None or not user.is_authenticated:
                raise serializers.ValidationError(
                    'Autenticação necessária para registar eventos de custódia (ADR-0017).'
                )
            if not access.can_append_custody(user, evidence, attrs.get('event_type')):
                raise serializers.ValidationError(
                    'Não tem permissão para registar eventos de custódia neste item '
                    '(ADR-0017): só o custódio atual, um membro da instituição que o '
                    'detém, o perito ou a autoridade do caso.'
                )
        return attrs


# ---------------------------------------------------------------------------
# CascadeCustodyRequest — payload para POST /api/custody/cascade/
# ---------------------------------------------------------------------------


class CascadeCustodyRequestSerializer(serializers.Serializer):
    """Payload do endpoint de eventos de custódia em cascata.

    Permite registar o mesmo evento (ex.: ``TRANSFERENCIA_CUSTODIA`` para
    ``LAB_PUBLICO`` no intake do ADR-0012) em N evidências (item-pai +
    sub-componentes) numa única operação atómica. As guardas do ledger e a
    validação de ownership são feitas por evidência dentro da view; este
    serializer apenas garante que o payload tem o formato correcto.
    """

    evidence_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=200,
        help_text='IDs das evidências a transitar (item principal + sub-componentes).',
    )
    event_type = serializers.ChoiceField(
        choices=EventType.choices,
        help_text='Tipo de evento a registar em todas as evidências.',
    )
    custodian_type = serializers.ChoiceField(
        choices=CustodianType.choices,
        required=False,
        allow_blank=True,
        default='',
        help_text='Custódio após o evento (opcional).',
    )
    observations = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        max_length=2000,
    )
    # Geolocalização/local do evento (ADR-0013) — aplicada a todas as evidências
    # da cascata. Opcional; coerência lat/lng validada abaixo.
    location_name = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=255
    )
    storage_location = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=120
    )
    gps_lat = serializers.DecimalField(
        max_digits=10, decimal_places=7, required=False, allow_null=True, default=None
    )
    gps_lng = serializers.DecimalField(
        max_digits=10, decimal_places=7, required=False, allow_null=True, default=None
    )
    gps_accuracy_m = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0
    )

    def validate(self, attrs):
        """Coerência GPS: latitude e longitude ambas presentes ou ambas ausentes."""
        try:
            validate_gps_coherence(attrs.get('gps_lat'), attrs.get('gps_lng'))
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from exc
        return attrs


# ---------------------------------------------------------------------------
# ActivityFeed — serializer read-only do feed de actividade sobre AuditLog (T06)
# ---------------------------------------------------------------------------


class ActivityFeedSerializer(serializers.ModelSerializer):
    """Serializa um ``AuditLog`` como item do feed de actividade (T06).

    Read-only: o feed é uma LEITURA do registo de auditoria, nunca uma
    escrita (o ``AuditLog`` é append-only e imutável). Cada item expõe os
    metadados crus (action/resource) com os respectivos rótulos legíveis, o
    autor da acção e uma frase pronta a exibir (``label``).

    O sinal ``is_priority_alert`` (ADR-0014 §7) destaca a criação de uma
    ocorrência prioritária. Para evitar N+1, o conjunto de ids de ocorrências
    prioritárias da página é pré-calculado pela view e injectado no
    ``context['priority_occurrence_ids']`` — o serializer apenas o consulta.
    """

    action_display = serializers.CharField(source='get_action_display', read_only=True)
    resource_type_display = serializers.CharField(
        source='get_resource_type_display', read_only=True
    )
    user = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()
    is_priority_alert = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            'id',
            'timestamp',
            'action',
            'action_display',
            'resource_type',
            'resource_type_display',
            'resource_id',
            'user',
            'user_name',
            'correlation_id',
            'is_priority_alert',
            'label',
        ]
        read_only_fields = fields

    def get_user(self, obj):
        """Username do autor da acção (``None`` se foi o sistema/anónimo)."""
        return obj.user.username if obj.user_id else None

    def get_user_name(self, obj):
        """Nome legível do autor: nome completo > username > 'sistema'."""
        if obj.user_id is None:
            return 'sistema'
        return get_user_display_name(obj.user)

    def get_is_priority_alert(self, obj):
        """True para criação de ocorrência PRIORITÁRIA (ADR-0014 §7).

        Só é alerta quando ``action=CREATE`` + ``resource_type=OCCURRENCE`` e
        a ocorrência referenciada existe e tem ``priority=PRIORITARIA``. A
        view pré-carrega os ids prioritários da página em
        ``context['priority_occurrence_ids']`` (evita N+1); se a ocorrência já
        não existir, o id não consta do conjunto e o resultado é False.
        """
        if (
            obj.action != AuditLog.Action.CREATE
            or obj.resource_type != AuditLog.ResourceType.OCCURRENCE
        ):
            return False
        priority_ids = self.context.get('priority_occurrence_ids', set())
        return obj.resource_id in priority_ids

    def get_label(self, obj):
        """Frase legível do evento (ex.: 'Ana Silva criou OCORRÊNCIA #12')."""
        actor = self.get_user_name(obj)
        verbo = {
            AuditLog.Action.CREATE: 'criou',
            AuditLog.Action.VIEW: 'consultou',
            AuditLog.Action.EXPORT_PDF: 'exportou PDF de',
            AuditLog.Action.EXPORT_CSV: 'exportou CSV de',
            AuditLog.Action.AUDIT_PURGE: 'expurgou',
            AuditLog.Action.SYSTEM_ALERT: 'alertou sobre',
        }.get(obj.action, obj.get_action_display().lower())
        recurso = obj.get_resource_type_display().upper()
        return f'{actor} {verbo} {recurso} #{obj.resource_id}'
