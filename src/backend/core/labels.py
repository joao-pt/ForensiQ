"""
ForensiQ — Rótulos e variantes de apresentação do estado legal derivado.

Fonte ÚNICA dos rótulos PT e da classe de cor (badge) dos estados legais
produzidos por :func:`core.models.derive_legal_state` (ADR-0015). Consumida pelo
render server-side (``frontend_views``) e pelo PDF (``pdf_export``) — antes estava
duplicada byte-a-byte nos dois. São dados de APRESENTAÇÃO (não comportamento): a
máquina de estados e os tipos de evento ficam em ``core.models``; aqui só o texto
e a cor. Editar um rótulo/cor (ou acrescentar o de um novo estado) faz-se SÓ aqui.
"""

# Rótulo PT de cada estado legal derivado.
LEGAL_STATE_LABELS = {
    'a_guarda_opc': 'À guarda do OPC',
    'validada': 'Validada',
    'em_pericia': 'Em perícia',
    'pericia_concluida': 'Perícia concluída',
    'encaminhada': 'Encaminhada',
    'restituida': 'Restituída',
    'perdida_favor_estado': 'Perdida a favor do Estado',
    'destruida': 'Destruída',
}

# Variante semântica do ponto do badge .state (a cor classifica o estado).
LEGAL_STATE_CSS = {
    'a_guarda_opc': 'info',
    'validada': 'info',
    'em_pericia': 'warn',
    'pericia_concluida': 'ok',
    'encaminhada': 'warn',
    'restituida': 'muted',
    'perdida_favor_estado': 'danger',
    'destruida': 'muted',
}
