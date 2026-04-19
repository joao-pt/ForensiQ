"""
ForensiQ — Validadores de identificadores forenses digitais.

Helpers puros, sem side effects nem queries. Pensados para serem chamados
a partir de `Model.clean()`, DRF serializers e testes. Todos levantam
`django.core.exceptions.ValidationError` com mensagens em PT-PT.

Referências:
- IMEI: 3GPP TS 23.003 § 6.2 — 15 dígitos, último é Luhn check.
- VIN: ISO 3779:2009 — 17 caracteres, letras I/O/Q proibidas.
- IMSI: 3GPP TS 23.003 § 2.2 — 14 ou 15 dígitos numéricos (MCC+MNC+MSIN).
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# IMEI — International Mobile Equipment Identity
# ---------------------------------------------------------------------------

_IMEI_RE = re.compile(r'^\d{15}$')


def _luhn_check(number: str) -> bool:
    """Valida o check digit de Luhn sobre uma string de dígitos.

    Algoritmo ISO/IEC 7812-1. Devolve True se o último dígito é o check
    digit correcto para os restantes. Aceita entrada já sanitizada (só
    dígitos) — o caller é responsável pela validação de formato.
    """
    total = 0
    # Percorre da direita para a esquerda; a partir do segundo dígito
    # (índice 1 a contar da direita), duplica e soma os dígitos do produto.
    for idx, ch in enumerate(reversed(number)):
        digit = ord(ch) - 48  # '0' == 48
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_imei(value: str) -> None:
    """Valida um IMEI (15 dígitos + check digit Luhn).

    Levanta ValidationError se:
    - Não forem 15 dígitos numéricos exactamente.
    - O check digit de Luhn falhar.

    Casos válidos reais incluem `490154203237518` (exemplo 3GPP).
    """
    if value is None:
        raise ValidationError('IMEI não pode ser nulo.')
    value = str(value).strip()
    if not _IMEI_RE.match(value):
        raise ValidationError(
            'IMEI inválido: deve conter exactamente 15 dígitos numéricos.'
        )
    if not _luhn_check(value):
        raise ValidationError(
            'IMEI inválido: falha na verificação do check digit (Luhn).'
        )


# ---------------------------------------------------------------------------
# VIN — Vehicle Identification Number (ISO 3779)
# ---------------------------------------------------------------------------

# ISO 3779: 17 caracteres alfanuméricos maiúsculos, exceptuando I, O, Q
# (para evitar confusão com 1 e 0).
_VIN_RE = re.compile(r'^[A-HJ-NPR-Z0-9]{17}$')
_VIN_FORBIDDEN = {'I', 'O', 'Q'}


def validate_vin(value: str) -> None:
    """Valida um VIN (17 caracteres ISO 3779).

    Levanta ValidationError se:
    - Não forem exactamente 17 caracteres.
    - Contiver letras proibidas (I, O, Q).
    - Contiver caracteres fora do alfanumérico maiúsculo.

    NOTA: a verificação do check digit (posição 9, só para VINs norte-
    americanos segundo FMVSS 115) NÃO é imposta aqui — muitos veículos
    europeus não cumprem a fórmula NHTSA, e uma validação estrita
    rejeitaria VINs válidos de fabricantes UE/Ásia. A verificação é
    delegada à API externa de lookup (vindecoder/NHTSA).
    """
    if value is None:
        raise ValidationError('VIN não pode ser nulo.')
    value = str(value).strip().upper()
    if len(value) != 17:
        raise ValidationError(
            'VIN inválido: deve conter exactamente 17 caracteres (ISO 3779).'
        )
    forbidden = _VIN_FORBIDDEN & set(value)
    if forbidden:
        raise ValidationError(
            'VIN inválido: não pode conter as letras '
            f'{", ".join(sorted(forbidden))} (ISO 3779).'
        )
    if not _VIN_RE.match(value):
        raise ValidationError(
            'VIN inválido: só são permitidos dígitos e letras maiúsculas '
            '(excepto I, O, Q).'
        )


# ---------------------------------------------------------------------------
# IMSI — International Mobile Subscriber Identity
# ---------------------------------------------------------------------------

_IMSI_RE = re.compile(r'^\d{14,15}$')


def validate_imsi(value: str) -> None:
    """Valida um IMSI (14 ou 15 dígitos numéricos, 3GPP TS 23.003)."""
    if value is None:
        raise ValidationError('IMSI não pode ser nulo.')
    value = str(value).strip()
    if not _IMSI_RE.match(value):
        raise ValidationError(
            'IMSI inválido: deve conter 14 ou 15 dígitos numéricos '
            '(MCC+MNC+MSIN).'
        )
