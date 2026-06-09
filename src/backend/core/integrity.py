"""
ForensiQ — Verificação de integridade da cadeia de custódia (consola forense).

Re-verifica o que o ledger já garante por construção: recalcula a cadeia de hash
encadeada de cada item (:meth:`ChainOfCustody.compute_record_hash`) e confirma que
nenhum registo foi adulterado nem nenhum elo partido; e deteta anomalias de
custódia (génese ausente, prova encaminhada por receber, custódio em falta) a
partir da sequência de eventos.

Só leitura, sem efeitos. A FÓRMULA do hash e o VOCABULÁRIO de eventos vivem nas
suas fontes únicas (``core.models`` / ``core.policy.event_states``) — aqui apenas
se RE-verifica a partir dos campos relidos da BD, nunca se reescreve. Qualquer
perito independente reproduz o mesmo cálculo (ISO/IEC 27037; ADR-0013).
"""

from .models import ChainOfCustody, Evidence
from .policy.event_states import GENESIS_EVENTS, EventType

# Hash semente do 1.º elo (sem registo anterior) — igual ao usado no save().
ZERO_HASH = '0' * 64


def _chains(evidence_ids, only_fields=None):
    """``{evidence_id: [registos ordenados por sequence]}`` para os itens dados.

    Carrega os registos diretamente do ledger (não da queryset da lente, que pode
    trazer ``select_related``/``only`` incompatíveis com o recálculo do hash),
    garantindo objetos completos e a ordem canónica por ``sequence``.
    """
    qs = ChainOfCustody.objects.filter(evidence_id__in=list(evidence_ids)).order_by(
        'evidence_id', 'sequence'
    )
    if only_fields:
        qs = qs.only(*only_fields)
    chains = {}
    for rec in qs:
        chains.setdefault(rec.evidence_id, []).append(rec)
    return chains


def _codes(evidence_ids):
    return dict(
        Evidence.objects.filter(id__in=list(evidence_ids)).values_list('id', 'code')
    )


def verify_chains(evidence_ids):
    """Recalcula e verifica a cadeia de hash de cada item.

    Para cada evidência, parte do hash semente e recalcula o ``record_hash`` de
    cada evento a partir do hash STORED do anterior; uma divergência denuncia
    adulteração de um campo ou um elo partido. Devolve um sumário e a lista de
    quebras (item + sequência + evento onde o hash deixa de bater certo).
    """
    chains = _chains(evidence_ids)
    codes = _codes(chains.keys())
    broken = []
    total_events = 0
    for ev_id, chain in chains.items():
        total_events += len(chain)
        prev = ZERO_HASH
        for rec in chain:
            expected = rec.compute_record_hash(previous_hash=prev)
            if expected != rec.record_hash:
                broken.append(
                    {
                        'code': codes.get(ev_id) or str(ev_id),
                        'sequence': rec.sequence,
                        'event': rec.get_event_type_display(),
                    }
                )
                break  # uma quebra basta para marcar a cadeia como comprometida
            prev = rec.record_hash
    total_items = len(chains)
    return {
        'total_items': total_items,
        'total_events': total_events,
        'broken': broken,
        'verified': total_items - len(broken),
        'intact': not broken,
    }


def detect_anomalies(evidence_ids):
    """Deteta anomalias de custódia na sequência de eventos de cada item.

    - **Génese ausente**: o 1.º evento não é uma génese (apreensão/derivação) —
      cadeia mal formada (severidade alta).
    - **Encaminhada por receber**: o último evento é um encaminhamento (item em
      trânsito, ainda sem receção — ADR-0016 v2) — severidade média.
    - **Custódio em falta**: um evento que não é génese sem ``custodian_type`` —
      elo fraco na cadeia (severidade média).
    """
    chains = _chains(
        evidence_ids,
        only_fields=('evidence_id', 'event_type', 'custodian_type', 'sequence'),
    )
    codes = _codes(chains.keys())
    findings = []
    for ev_id, chain in chains.items():
        code = codes.get(ev_id) or str(ev_id)
        first, last = chain[0], chain[-1]
        if first.event_type not in GENESIS_EVENTS:
            findings.append(
                {
                    'code': code,
                    'severity': 'alta',
                    'msg': f'Primeiro evento não é génese ({first.get_event_type_display()}).',
                }
            )
        if last.event_type == EventType.ENCAMINHAMENTO_CUSTODIA:
            findings.append(
                {
                    'code': code,
                    'severity': 'media',
                    'msg': 'Encaminhada e ainda não recebida (em trânsito).',
                }
            )
        missing = next(
            (r for r in chain if r.event_type not in GENESIS_EVENTS and not r.custodian_type),
            None,
        )
        if missing:
            findings.append(
                {
                    'code': code,
                    'severity': 'media',
                    'msg': f'Evento sem custódio definido (sequência {missing.sequence}).',
                }
            )
    # Severidade alta primeiro, depois por código.
    findings.sort(key=lambda f: (f['severity'] != 'alta', f['code']))
    return findings
