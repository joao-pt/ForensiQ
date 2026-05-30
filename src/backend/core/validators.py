"""
ForensiQ — Validadores de identificadores forenses digitais.

Helpers puros, sem side effects nem queries. Pensados para serem chamados
a partir de `Model.clean()`, DRF serializers e testes. Todos levantam
`django.core.exceptions.ValidationError` com mensagens em PT-PT.

Além das funções bloqueantes (`validate_imei`, `validate_vin`,
`validate_imsi`), oferece funções "advisory" que devolvem mensagens de
aviso sem levantar excepção — úteis para casos onde a estrutura é válida
mas há suspeita de erro de transcrição (VIN check digit ISO 3779, MCC
IMSI fora de PT/UE).

Referências:
- IMEI: 3GPP TS 23.003 § 6.2 — 15 dígitos, último é Luhn check.
- VIN: ISO 3779:2009 — 17 caracteres, letras I/O/Q proibidas, 9.º carácter
  é check digit calculado segundo FMVSS 115 (não obrigatório fora dos EUA).
- IMSI: 3GPP TS 23.003 § 2.2 — 14 ou 15 dígitos numéricos (MCC+MNC+MSIN);
  MCC 268 é Portugal (3GPP TS 23.122).
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

# Tabela de transliteração para o cálculo do check digit (FMVSS 115).
# Letras I, O, Q estão deliberadamente ausentes — se aparecerem, o VIN
# já foi rejeitado por `validate_vin`.
_VIN_VALUES = {
    'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5, 'F': 6, 'G': 7, 'H': 8,
    'J': 1, 'K': 2, 'L': 3, 'M': 4, 'N': 5,
    'P': 7, 'R': 9,
    'S': 2, 'T': 3, 'U': 4, 'V': 5, 'W': 6, 'X': 7, 'Y': 8, 'Z': 9,
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
    '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def _vin_check_digit_valid(vin: str) -> bool:
    """Calcula o check digit ISO 3779 (posição 9) e compara com o presente.

    Algoritmo FMVSS 115:
    1. Translitera cada carácter via `_VIN_VALUES`.
    2. Multiplica por pesos `_VIN_WEIGHTS` (posições 1-17).
    3. Soma os produtos e calcula `s % 11`. Se for 10 → 'X', senão dígito.

    Caller deve garantir que `vin` já passou `validate_vin` (17 chars,
    sem I/O/Q). Devolve True se o check digit confere.
    """
    try:
        total = sum(_VIN_VALUES[c] * w for c, w in zip(vin, _VIN_WEIGHTS, strict=False))
    except KeyError:
        return False
    remainder = total % 11
    expected = 'X' if remainder == 10 else str(remainder)
    return vin[8] == expected


def validate_vin(value: str) -> None:
    """Valida um VIN (17 caracteres ISO 3779).

    Levanta ValidationError se:
    - Não forem exactamente 17 caracteres.
    - Contiver letras proibidas (I, O, Q).
    - Contiver caracteres fora do alfanumérico maiúsculo.

    NOTA: a verificação do check digit (posição 9, só para VINs norte-
    americanos segundo FMVSS 115) NÃO é imposta aqui — muitos veículos
    europeus não cumprem a fórmula NHTSA, e uma validação estrita
    rejeitaria VINs válidos de fabricantes UE/Ásia. Para alertar (sem
    bloquear) sobre check digit suspeito, usar `validate_vin_advisory`.
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


def validate_vin_advisory(value: str) -> str | None:
    """Devolve mensagem de aviso para VINs com check digit ISO 3779 errado.

    Não levanta excepção — caller decide se mostra como warning ao
    utilizador. Útil para distinguir veículos norte-americanos (onde a
    fórmula FMVSS 115 é obrigatória) de veículos europeus/asiáticos (onde
    o check digit muitas vezes não cumpre a fórmula NHTSA).

    Retorna `None` se:
    - `value` é nulo
    - VIN é estruturalmente inválido (caller já apanha via `validate_vin`)
    - Check digit confere
    """
    if value is None:
        return None
    v = str(value).strip().upper()
    if len(v) != 17 or not _VIN_RE.match(v):
        return None
    if not _vin_check_digit_valid(v):
        return (
            'VIN aceite, mas o 9.º carácter não corresponde ao check digit '
            'ISO 3779. Pode ser um veículo europeu (fórmula NHTSA não aplica) '
            'ou um erro de transcrição. Confirme manualmente.'
        )
    return None


# ---------------------------------------------------------------------------
# IMSI — International Mobile Subscriber Identity
# ---------------------------------------------------------------------------

_IMSI_RE = re.compile(r'^\d{14,15}$')

# 3GPP TS 23.122 — Portugal + códigos UE mais comuns para tráfego forense.
# Operadores fora desta lista (long-haul roaming, MVNOs raros) ainda são
# aceites por `validate_imsi`; `validate_imsi_advisory` regista aviso.
_KNOWN_MCC = {
    '268',  # Portugal
    '214',  # Espanha
    '208',  # França
    '262',  # Alemanha
    '202',  # Grécia
    '222',  # Itália
    '204',  # Países Baixos
    '206',  # Bélgica
    '234',  # Reino Unido
    '272',  # Irlanda
    '226',  # Roménia
    '230',  # Chéquia
    '231',  # Eslováquia
    '232',  # Áustria
    '238',  # Dinamarca
    '240',  # Suécia
    '242',  # Noruega
    '244',  # Finlândia
    '260',  # Polónia
    '293',  # Eslovénia
}


def validate_imsi(value: str) -> None:
    """Valida um IMSI (14 ou 15 dígitos numéricos, 3GPP TS 23.003).

    Levanta ValidationError em formato inválido. Não verifica MCC — para
    avisar sobre MCC desconhecido sem bloquear, usar `validate_imsi_advisory`.
    """
    if value is None:
        raise ValidationError('IMSI não pode ser nulo.')
    value = str(value).strip()
    if not _IMSI_RE.match(value):
        raise ValidationError(
            'IMSI inválido: deve conter 14 ou 15 dígitos numéricos '
            '(MCC+MNC+MSIN).'
        )


def validate_imsi_advisory(value: str) -> str | None:
    """Devolve mensagem de aviso se o MCC do IMSI não é PT/UE comum.

    Não levanta excepção — caller decide. Retorna `None` se o IMSI é
    estruturalmente inválido (caller já apanha) ou se o MCC está na lista
    conhecida (`_KNOWN_MCC`).
    """
    if value is None:
        return None
    v = str(value).strip()
    if not _IMSI_RE.match(v):
        return None
    if v[:3] not in _KNOWN_MCC:
        return (
            f'MCC "{v[:3]}" não corresponde a Portugal (268) nem a operador '
            'UE comum. Confirme se é roaming internacional ou erro de transcrição.'
        )
    return None
