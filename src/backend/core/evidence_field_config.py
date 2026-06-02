"""
ForensiQ — Configuração dos campos de caracterização por tipo de evidência.

Fonte ÚNICA (server-side) dos campos guardados em ``Evidence.type_specific_data``
(JSONField). Consumida por:
  - ``frontend_views`` — render do bloco de campos por tipo no formulário;
  - ``models._validate_type_specific_data`` / ``serializers`` — presença
    (``required``) + validadores de formato;
  - PDF / serializers — apresentação (mascarando os sensíveis).

Render a partir desta config mata o drift backend↔frontend: nenhum campo é
hardcoded no template. Adicionar um campo é editar SÓ este ficheiro.

Decisão (João, 2026-06-02): formulário LEAN para recolha no terreno. Muitos
campos tornam o registo um pesadelo e muitos nem são visíveis ao agente. Logo:
  - transversais mínimos (marca, modelo; o nº de série é campo próprio do
    modelo, não entra aqui);
  - por tipo, sobretudo os IDENTIFICADORES (IMEI/IMSI/ICCID/VIN/MAC) e 1–2
    campos críticos; o resto fica para o laboratório.
  - campos ``sensitive`` (passcode/PIN) são mascarados na UI/PDF e cifrados.

Suporte de pesquisa (spec completa em ``_cowork/device_fields_spec.json``):
NIST SP 800-101r1, SWGDE 17-F-002/18-F-002/003, ISO/IEC 27037, ACPO.

Chaves dos campos:
  key       — nome em ``type_specific_data`` (snake_case);
  label     — rótulo PT-PT;
  input     — text | number | select | tel;
  options   — lista (só para input=select);
  required  — bool (default False);
  validator — 'imei' | 'imsi' | 'iccid' | 'vin' | 'mac' (formato; reutiliza os
              validadores existentes do modelo). Sem validator = texto livre;
  lookup    — 'imei' | 'vin' (liga ao botão de consulta externa, se existir);
  sensitive — bool; mascarar na UI/PDF e cifrar ao nível da aplicação.
"""

from __future__ import annotations

# Campos comuns a TODOS os tipos (em type_specific_data). O serial_number é
# campo próprio do modelo Evidence — não duplicar aqui.
TRANSVERSAL_FIELDS = [
    {'key': 'marca', 'label': 'Marca / Fabricante', 'input': 'text'},
    {'key': 'modelo', 'label': 'Modelo', 'input': 'text'},
]

# Campos específicos por tipo (LEAN — identificadores + poucos críticos).
EVIDENCE_TYPE_FIELDS: dict[str, list[dict]] = {
    'MOBILE_DEVICE': [
        {'key': 'imei', 'label': 'IMEI', 'input': 'text', 'validator': 'imei', 'lookup': 'imei'},
        {'key': 'imei_2', 'label': 'IMEI secundário (dual-SIM)', 'input': 'text', 'validator': 'imei'},
        {'key': 'operating_system', 'label': 'Sistema operativo', 'input': 'select',
         'options': ['Android', 'iOS / iPadOS', 'Outro', 'Desconhecido']},
        {'key': 'passcode', 'label': 'Código de desbloqueio (se autorizado)', 'input': 'text', 'sensitive': True},
    ],
    'SIM_CARD': [
        {'key': 'imsi', 'label': 'IMSI', 'input': 'text', 'validator': 'imsi'},
        {'key': 'iccid', 'label': 'ICCID', 'input': 'text', 'validator': 'iccid'},
        {'key': 'carrier', 'label': 'Operador', 'input': 'text'},
        {'key': 'pin_code', 'label': 'PIN (se autorizado)', 'input': 'text', 'sensitive': True},
    ],
    'VEHICLE': [
        {'key': 'vin', 'label': 'VIN', 'input': 'text', 'validator': 'vin', 'lookup': 'vin'},
    ],
    'VEHICLE_COMPONENT': [
        {'key': 'associated_vin', 'label': 'VIN do veículo associado', 'input': 'text', 'validator': 'vin'},
    ],
    'NETWORK_DEVICE': [
        {'key': 'mac', 'label': 'MAC', 'input': 'text', 'validator': 'mac'},
    ],
    'IOT_DEVICE': [
        {'key': 'mac', 'label': 'MAC', 'input': 'text', 'validator': 'mac'},
    ],
    'GPS_TRACKER': [
        {'key': 'imei', 'label': 'IMEI', 'input': 'text', 'validator': 'imei'},
        {'key': 'imsi', 'label': 'IMSI', 'input': 'text', 'validator': 'imsi'},
    ],
    'SMART_TAG': [
        {'key': 'tag_ecosystem', 'label': 'Ecossistema', 'input': 'select',
         'options': ['Apple AirTag', 'Samsung SmartTag', 'Tile', 'Chipolo', 'Outro', 'Desconhecido']},
        {'key': 'device_serial_number', 'label': 'Nº de série do localizador', 'input': 'text'},
    ],
    'COMPUTER': [
        {'key': 'operating_system', 'label': 'Sistema operativo', 'input': 'text'},
        {'key': 'encryption_status', 'label': 'Cifragem de disco', 'input': 'select',
         'options': ['Sem cifragem', 'BitLocker', 'FileVault', 'LUKS', 'Outra', 'Desconhecido']},
    ],
    'INTERNAL_DRIVE': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
        {'key': 'interface', 'label': 'Interface', 'input': 'select',
         'options': ['SATA', 'NVMe', 'SAS', 'IDE/PATA', 'USB', 'Outro', 'Desconhecido']},
    ],
    'STORAGE_MEDIA': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
    ],
    'MEMORY_CARD': [
        {'key': 'capacity', 'label': 'Capacidade', 'input': 'text'},
    ],
    'CCTV_DEVICE': [
        {'key': 'channels', 'label': 'Nº de canais', 'input': 'number'},
        {'key': 'system_datetime', 'label': 'Data/hora do sistema na recolha', 'input': 'text'},
    ],
    'DRONE': [
        {'key': 'aircraft_serial_number', 'label': 'Nº de série da aeronave', 'input': 'text'},
    ],
    'GAMING_CONSOLE': [
        {'key': 'console_id', 'label': 'ID da consola', 'input': 'text'},
    ],
    'DIGITAL_FILE': [
        {'key': 'source_device_description', 'label': 'Dispositivo-fonte (descrição)', 'input': 'text'},
    ],
    'RFID_NFC_CARD': [
        {'key': 'card_uid', 'label': 'UID do cartão', 'input': 'text'},
    ],
    'OTHER_DIGITAL': [
        {'key': 'device_category', 'label': 'Categoria do dispositivo', 'input': 'text'},
    ],
}


def fields_for(evidence_type: str) -> list[dict]:
    """Campos específicos de um EvidenceType (lista vazia se não houver)."""
    return EVIDENCE_TYPE_FIELDS.get(evidence_type, [])


def all_fields_for(evidence_type: str) -> list[dict]:
    """Transversais + específicos, na ordem de apresentação."""
    return TRANSVERSAL_FIELDS + fields_for(evidence_type)


def all_keys() -> set[str]:
    """Todas as chaves conhecidas de type_specific_data (transversais + tipos)."""
    keys = {f['key'] for f in TRANSVERSAL_FIELDS}
    for fields in EVIDENCE_TYPE_FIELDS.values():
        keys.update(f['key'] for f in fields)
    return keys


def sensitive_keys() -> set[str]:
    """Chaves a mascarar/cifrar (passcode, PIN, …)."""
    keys = set()
    for fields in EVIDENCE_TYPE_FIELDS.values():
        keys.update(f['key'] for f in fields if f.get('sensitive'))
    return keys
