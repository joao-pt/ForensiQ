"""
ForensiQ — Acesso à configuração de campos por tipo de evidência.

A configuração VIVE na base de dados (``EvidenceFieldDef`` + ``FieldOption``),
editável no admin — fonte ÚNICA, sem hardcode (semeada por
``0027_seed_evidence_fields``). Este módulo é a API de LEITURA: converte as linhas
para os dicts que o render do formulário (``frontend_views``), a validação
(``models.Evidence._validate_type_specific_data`` / ``serializers``) e o PDF
consomem — mantendo a mesma forma de sempre (``{key, label, input, options?,
required?, validator?, lookup?, sensitive?}``), pelo que os consumidores não mudam.

Os VALIDADORES de formato (IMEI/IMSI/ICCID/VIN/MAC) ficam em código
(``core.validators``): a coluna ``validator`` só refere, por nome, uma função que
existe — nunca se cria um campo cujo validador não exista.
"""

from __future__ import annotations


def _to_dict(field) -> dict:
    """``EvidenceFieldDef`` (com ``options`` pré-carregadas) → dict consumido pela UI/validação."""
    d = {'key': field.key, 'label': field.label, 'input': field.input}
    if field.required:
        d['required'] = True
    if field.validator:
        d['validator'] = field.validator
    if field.lookup:
        d['lookup'] = field.lookup
    if field.sensitive:
        d['sensitive'] = True
    if field.input == 'select':
        d['options'] = [o.value for o in field.options.all()]
    return d


def _active_qs(evidence_type=None, *, exclude_transversal=False, ordered=False):
    """Queryset BASE dos campos ativos com ``options`` pré-carregadas — fonte
    única do recorte (auditoria D51); as funções públicas só parametrizam."""
    from core.models import EvidenceFieldDef

    qs = EvidenceFieldDef.objects.filter(is_active=True).prefetch_related('options')
    if evidence_type is not None:
        qs = qs.filter(evidence_type=evidence_type)
    if exclude_transversal:
        qs = qs.exclude(evidence_type='')
    if ordered:
        qs = qs.order_by('evidence_type', 'order', 'key')
    return qs


def transversal_fields() -> list[dict]:
    """Campos comuns a todos os tipos (``evidence_type`` vazio)."""
    return [_to_dict(f) for f in _active_qs('')]


def fields_for(evidence_type: str) -> list[dict]:
    """Campos específicos de um ``EvidenceType`` (lista vazia se não houver)."""
    if not evidence_type:
        return []
    return [_to_dict(f) for f in _active_qs(evidence_type)]


def type_fields_flat() -> list[dict]:
    """TODOS os campos por-tipo, planos, cada um marcado com ``type`` (o JS
    mostra/esconde por tipo). Substitui a antiga iteração de ``EVIDENCE_TYPE_FIELDS``."""
    qs = _active_qs(exclude_transversal=True, ordered=True)
    return [{**_to_dict(f), 'type': f.evidence_type} for f in qs]


def validate_type_specific_data(evidence_type: str, data: dict | None) -> list[str]:
    """Aplica os validadores de formato dos campos do tipo a ``data``.

    Fonte ÚNICA partilhada por ``models.Evidence._validate_type_specific_data`` e
    ``serializers.EvidenceSerializer.validate``. Devolve a lista de problemas (uma
    entrada por campo inválido — NÃO sobrepõe). Lista vazia = válido.
    """
    from django.core.exceptions import ValidationError

    from core.validators import (
        validate_iccid,
        validate_imei,
        validate_imsi,
        validate_mac,
        validate_vin,
    )

    validators = {
        'imei': validate_imei,
        'imsi': validate_imsi,
        'iccid': validate_iccid,
        'vin': validate_vin,
        'mac': validate_mac,
    }
    data = data or {}
    problems: list[str] = []
    for field in fields_for(evidence_type):
        name = field.get('validator')
        value = data.get(field['key'])
        if name and value:
            try:
                validators[name](value)
            except ValidationError as exc:
                problems.append(f'{field["key"]}: {"; ".join(exc.messages)}')
    return problems


def fields_by_type() -> dict[str, list]:
    """TODOS os campos ativos agrupados por ``evidence_type`` (``''`` = transversal),
    num ÚNICO query enxuto (sem ``options`` — a exibição mostra o valor gravado, não
    a lista de opções). Catálogo para laços que resolvem muitos itens sem N+1:
    construir uma vez e passar a :func:`display_fields_for` por cada item.
    """
    from core.models import EvidenceFieldDef

    grouped: dict[str, list] = {}
    qs = (
        EvidenceFieldDef.objects.filter(is_active=True)
        .order_by('evidence_type', 'order', 'key')
        .only('evidence_type', 'key', 'label', 'sensitive', 'is_identifier')
    )
    for field in qs:
        grouped.setdefault(field.evidence_type, []).append(field)
    return grouped


def display_fields_for(
    evidence, catalog: dict[str, list] | None = None, *, identifiers_only: bool = False
) -> list[dict]:
    """Pares ``{key, label, value}`` RESOLVIDOS de ``type_specific_data`` para
    EXIBIÇÃO (guia de transporte, detalhe do item).

    Junta os campos TRANSVERSAIS (marca/modelo/…) + os do TIPO do item, pela ordem
    da config (fonte única ``EvidenceFieldDef``), traduzindo cada ``key`` para o seu
    rótulo. OMITE sempre os campos ``sensitive`` (passcode/PIN) e os SEM valor — a
    guia identifica o dispositivo, não expõe segredos nem linhas vazias.

    ``identifiers_only``: só os campos marcados como IDENTIFICADOR (``is_identifier``)
    — marca/modelo/IMEI/VIN/…; exclui metadados forenses (sistema operativo, operador,
    capacidade). É o subconjunto que a guia de transporte mostra.
    ``catalog``: passar :func:`fields_by_type` (uma vez) quando se resolvem muitos
    itens, para evitar N+1; omisso, é obtido aqui (custo de 1 query).
    """
    catalog = catalog if catalog is not None else fields_by_type()
    data = evidence.type_specific_data or {}
    out: list[dict] = []
    for field in [*catalog.get('', []), *catalog.get(evidence.type, [])]:
        if field.sensitive:
            continue
        if identifiers_only and not field.is_identifier:
            continue
        value = data.get(field.key)
        if value in (None, '', [], {}):
            continue
        out.append({'key': field.key, 'label': field.label, 'value': value})
    return out


def all_keys() -> set[str]:
    """Todas as chaves conhecidas de ``type_specific_data`` (transversais + tipos)."""
    from core.models import EvidenceFieldDef

    return set(
        EvidenceFieldDef.objects.filter(is_active=True).values_list('key', flat=True)
    )


def sensitive_keys() -> set[str]:
    """Chaves a mascarar/cifrar (passcode, PIN, …)."""
    from core.models import EvidenceFieldDef

    return set(
        EvidenceFieldDef.objects.filter(is_active=True, sensitive=True).values_list(
            'key', flat=True
        )
    )
