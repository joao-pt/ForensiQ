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
    'UPDATE': 'info',
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
    'UPDATE': 'Atualização',
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

# Consulta dos atos (badge clicável → modal read-only): espelho de APRESENTAÇÃO
# da flag ``validation_overdue`` do registo (policy ``validation_acted_late``)
# — a validação fora do prazo legal é aceite e fica assinalada, não bloqueia
# (daí âmbar, não vermelho).
VALIDATION_LATE_LABEL = 'Fora do prazo legal'
VALIDATION_LATE_CSS = 'warn'

# Badge do DESPACHO judicial para perícia (CPP art. 154.º/158.º) — facto do
# ledger (core.utils.has_despacho), não trabalho pendente: informa que a
# perícia foi ordenada por autoridade judiciária, daí 'info' e não 'ok'/'warn'.
DESPACHO_BADGE_LABEL = 'Com despacho judicial'
DESPACHO_BADGE_CSS = 'info'

# Arquivo (parecer UX item 14): badge do processo CONCLUÍDO no detalhe, rótulo
# da síntese quando os itens têm desfechos DIFERENTES (coluna Desfecho do
# Arquivo) e aviso não-bloqueante das superfícies de escrita num processo
# arquivado. Nota de policy: eventos de custódia nunca DES-arquivam um processo
# (a perda domina os atos posteriores; restituição/destruição fecham o ledger)
# — só o registo de um item NOVO o devolve às listas ativas.
ARQUIVO_BADGE_LABEL = 'Concluído — no Arquivo'
ARQUIVO_BADGE_CSS = 'muted'
DESFECHO_MISTO_LABEL = 'Misto'
ARQUIVO_REOPEN_HINT = (
    'Este processo está concluído (no Arquivo): o registo acrescenta '
    'atividade a um processo arquivado — legítimo (ex.: restituição '
    'decidida após a perda a favor do Estado), mas deve ser deliberado.'
)

# Página «Atos de autoridade» (consulta global — grupo Análise): badge do ATO
# por tipo de evento — rótulo CURTO de coluna (o completo do enum fica no
# filtro e no modal; numa coluna de grelha truncava) e cor da paleta existente
# (a validação pinta-se como o estatuto «validada», o despacho como o badge do
# despacho). Estatuto compacto do PRAZO por linha — vocabulário do modal
# _atos_info (prazo cumprido pela CONCLUSAO posterior; extinto pela disposição
# final) + o despacho NÃO-vigente (Art. 158.º: vale o último; os anteriores
# ficam substituídos, o prazo deles já não corre).
ACT_EVENT_SHORT = {
    'VALIDACAO_APREENSAO': 'Validação',
    'DESPACHO_PERICIA': 'Despacho',
}
ACT_EVENT_CSS = {
    'VALIDACAO_APREENSAO': VALIDATION_STATUS_CSS['validada'],
    'DESPACHO_PERICIA': DESPACHO_BADGE_CSS,
}
PRAZO_RESOLVIDO_LABELS = {
    'cumprido': 'Prazo cumprido',
    'extinto': 'Prazo extinto',
}
PRAZO_RESOLVIDO_CSS = {
    'cumprido': 'ok',
    'extinto': 'muted',
}
DESPACHO_SUBSTITUIDO_LABEL = 'Substituído'
DESPACHO_SUBSTITUIDO_CSS = 'muted'

# Rótulo + cor do PRAZO da perícia ordenada (data-limite derivada do despacho:
# core.policy.event_states.pericia_deadline). ``{due}`` é a data-limite
# (YYYY-MM-DD) e ``{rel}`` a urgência relativa («hoje»/«amanhã»/«em N dias») —
# formatados em frontend_views._pericia_badge (fonte única do format).
PERICIA_DEADLINE_LABELS = {
    'em_prazo': 'Perícia até {due}',
    'a_vencer': 'Perícia até {due} — vence {rel}',
    'vencida': 'Prazo da perícia vencido ({due})',
}
PERICIA_DEADLINE_CSS = {
    'em_prazo': 'info',     # informação: a perícia está ordenada e no prazo
    'a_vencer': 'warn',     # atenção: a data-limite aproxima-se
    'vencida': 'danger',
}
