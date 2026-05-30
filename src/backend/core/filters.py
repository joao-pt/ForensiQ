"""FilterSets DRF para endpoints de listagem (modo tabela densa).

Mantemos URLs limpas (``?date_after=2026-01-01``) em vez de
``?date_time__gte=...`` para reduzir ruído na barra de endereços e na
documentação OpenAPI. Os filtros são minimalistas — apenas os campos
realmente expostos na sidebar do data-table; queries arbitrárias passam
pelo ``SearchFilter`` ou ``OrderingFilter``.
"""

from django_filters import rest_framework as filters

from .models import (
    LEGAL_STATES,
    ChainOfCustody,
    EventType,
    Evidence,
    Occurrence,
    derive_legal_state,
)


class OccurrenceFilter(filters.FilterSet):
    """Filtros para ``/api/occurrences/``."""

    date_after = filters.DateFilter(field_name='date_time', lookup_expr='gte')
    date_before = filters.DateFilter(field_name='date_time', lookup_expr='lte')
    has_gps = filters.BooleanFilter(method='filter_has_gps')

    class Meta:
        model = Occurrence
        fields = ['date_after', 'date_before', 'has_gps']

    def filter_has_gps(self, queryset, name, value):
        # `gps_lat` e `gps_lng` são preenchidos em par (validado em clean()).
        return (
            queryset.exclude(gps_lat__isnull=True)
            if value
            else queryset.filter(gps_lat__isnull=True)
        )


class EvidenceFilter(filters.FilterSet):
    """Filtros para ``/api/evidences/``.

    O filtro ``state`` continua tratado em ``EvidenceViewSet.get_queryset``
    (depende de ``with_current_state`` via subquery, fora do schema do
    ModelFilter). Mantemos coerência com a queixa de UX 2026-05-02.
    """

    type = filters.MultipleChoiceFilter(
        field_name='type',
        choices=Evidence.EvidenceType.choices,
    )
    date_after = filters.DateFilter(
        field_name='timestamp_seizure', lookup_expr='gte',
    )
    date_before = filters.DateFilter(
        field_name='timestamp_seizure', lookup_expr='lte',
    )
    has_gps = filters.BooleanFilter(method='filter_has_gps')

    class Meta:
        model = Evidence
        fields = ['type', 'date_after', 'date_before', 'has_gps']

    def filter_has_gps(self, queryset, name, value):
        return (
            queryset.exclude(gps_lat__isnull=True)
            if value
            else queryset.filter(gps_lat__isnull=True)
        )


class CustodyFilter(filters.FilterSet):
    """Filtros para ``/api/custody/`` (ledger de eventos, ADR-0015).

    ``event_type`` filtra directamente a coluna (enum). ``legal_state``
    filtra pelo estado legal DERIVADO da sequência de eventos da evidência
    — não há coluna 1:1, logo é um filtro de método que selecciona as
    evidências cujo estado derivado coincide e devolve os seus eventos.
    """

    event_type = filters.MultipleChoiceFilter(
        field_name='event_type',
        choices=EventType.choices,
    )
    legal_state = filters.ChoiceFilter(
        method='filter_legal_state',
        choices=[(s, s) for s in sorted(LEGAL_STATES)],
    )
    date_after = filters.DateFilter(field_name='timestamp', lookup_expr='gte')
    date_before = filters.DateFilter(field_name='timestamp', lookup_expr='lte')

    class Meta:
        model = ChainOfCustody
        fields = ['event_type', 'legal_state', 'date_after', 'date_before']

    def filter_legal_state(self, queryset, name, value):
        # Estado legal derivado não é coluna — computa-se por evidência sobre
        # a sequência de eventos. Identifica as evidências cujo estado derivado
        # coincide e devolve só os registos dessas evidências.
        if not value:
            return queryset
        evidence_ids = {ev_id for ev_id, _ in queryset.values_list('evidence_id', 'id')}
        matched = []
        for ev_id in evidence_ids:
            eventos = list(
                ChainOfCustody.objects.filter(evidence_id=ev_id).order_by('sequence')
            )
            if derive_legal_state(eventos) == value:
                matched.append(ev_id)
        return queryset.filter(evidence_id__in=matched)
