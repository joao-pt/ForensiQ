"""
ForensiQ — Rótulos e variantes de apresentação do estado legal derivado.

Fonte ÚNICA dos rótulos PT e da classe de cor (badge) dos estados legais
produzidos por :func:`core.models.derive_legal_state` (ADR-0015). Consumida pelo
render server-side (``frontend_views``) e pelo PDF (``pdf_export``) — antes estava
duplicada byte-a-byte nos dois. São dados de APRESENTAÇÃO (não comportamento): a
máquina de estados e os tipos de evento ficam em ``core.models``; aqui só o texto
e a cor. Editar um rótulo/cor (ou acrescentar o de um novo estado) faz-se SÓ aqui.
"""

# Rótulo PT de cada estado legal derivado (eixo de custódia/localização; a
# validação da apreensão é eixo próprio — VALIDATION_STATUS_LABELS abaixo).
LEGAL_STATE_LABELS = {
    'a_guarda_opc': 'À guarda do OPC',
    'em_pericia': 'Em perícia',
    'pericia_concluida': 'Perícia concluída',
    'em_transito': 'Em trânsito',
    'encaminhada': 'Encaminhada',
    'restituida': 'Restituída',
    'perdida_favor_estado': 'Perdida a favor do Estado',
    'destruida': 'Destruída',
}

# Variante semântica da cor das AÇÕES de auditoria no feed (mesma paleta dos
# badges .state; auditoria D97). Ações fora do mapa ficam neutras (sem classe).
ACTION_CSS = {
    'CREATE': 'ok',
    'EXPORT_PDF': 'info',
    'EXPORT_CSV': 'info',
    'SYSTEM_ALERT': 'danger',
}

# Rótulo CURTO da ação no feed — uma linha por evento, em ritmo de diário de
# bordo (os rótulos completos do enum partiam a coluna em 3-4 linhas). O rótulo
# completo continua disponível (title/detalhe). Ações fora do mapa caem no
# rótulo completo do próprio enum.
ACTION_SHORT = {
    'VIEW': 'Visualização',
    'CREATE': 'Criação',
    'EXPORT_PDF': 'Export. PDF',
    'EXPORT_CSV': 'Export. CSV',
    'AUDIT_PURGE': 'Expurgo RGPD',
    'SYSTEM_ALERT': 'Alerta',
}

# Variante semântica do ponto do badge .state (a cor classifica o estado).
LEGAL_STATE_CSS = {
    'a_guarda_opc': 'info',
    'em_pericia': 'warn',
    'pericia_concluida': 'ok',
    'em_transito': 'warn',
    'encaminhada': 'warn',
    'restituida': 'muted',
    'perdida_favor_estado': 'danger',
    'destruida': 'muted',
}

# Rótulo + cor do ESTATUTO DE VALIDAÇÃO da apreensão (eixo ortogonal ao estado
# de custódia — core.policy.event_states.validation_status; CPP art. 178.º/6).
VALIDATION_STATUS_LABELS = {
    'validada': 'Validada',
    'por_validar': 'Por validar',
    'em_atraso': 'Validação em atraso',
}
VALIDATION_STATUS_CSS = {
    'validada': 'ok',
    'por_validar': 'warn',   # trabalho pendente dentro do prazo = âmbar
    'em_atraso': 'danger',
}
