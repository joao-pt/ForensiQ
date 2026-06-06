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


def transversal_fields() -> list[dict]:
    """Campos comuns a todos os tipos (``evidence_type`` vazio)."""
    from core.models import EvidenceFieldDef

    qs = (
        EvidenceFieldDef.objects.filter(evidence_type='', is_active=True)
        .prefetch_related('options')
    )
    return [_to_dict(f) for f in qs]


def fields_for(evidence_type: str) -> list[dict]:
    """Campos específicos de um ``EvidenceType`` (lista vazia se não houver)."""
    from core.models import EvidenceFieldDef

    if not evidence_type:
        return []
    qs = (
        EvidenceFieldDef.objects.filter(evidence_type=evidence_type, is_active=True)
        .prefetch_related('options')
    )
    return [_to_dict(f) for f in qs]


def type_fields_flat() -> list[dict]:
    """TODOS os campos por-tipo, planos, cada um marcado com ``type`` (o JS
    mostra/esconde por tipo). Substitui a antiga iteração de ``EVIDENCE_TYPE_FIELDS``."""
    from core.models import EvidenceFieldDef

    qs = (
        EvidenceFieldDef.objects.exclude(evidence_type='')
        .filter(is_active=True)
        .prefetch_related('options')
        .order_by('evidence_type', 'order', 'key')
    )
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
