"""FilterSets DRF para endpoints de listagem (modo tabela densa).

Mantemos URLs limpas (``?date_after=2026-01-01``) em vez de
``?date_time__gte=...`` para reduzir ruído na barra de endereços e na
documentação OpenAPI. Os filtros são minimalistas — apenas os campos
realmente expostos na sidebar do data-table; queries arbitrárias passam
pelo ``SearchFilter`` ou ``OrderingFilter``.
"""

from django_filters import rest_framework as filters

from .models import ChainOfCustody, Evidence, Occurrence


class OccurrenceFilter(filters.FilterSet):
    """Filtros para ``/api/occurrences/``."""

    date_after = filters.DateFilter(field_name='date_time', lookup_expr='gte')
    date_before = filters.DateFilter(field_name='date_time', lookup_expr='lte')
    has_gps = filters.BooleanFilter(method='filter_has_gps')

    class Meta:
        model = Occurrence
        fields = ['date_after', 'date_before', 'has_gps']

    def filter_has_gps(self, queryset, name, value):
        # `gps_lat` e `gps_lon` são preenchidos em par (validado em clean()).
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
    """Filtros para ``/api/custody/``."""

    new_state = filters.MultipleChoiceFilter(
        field_name='new_state',
        choices=ChainOfCustody.CustodyState.choices,
    )
    date_after = filters.DateFilter(field_name='timestamp', lookup_expr='gte')
    date_before = filters.DateFilter(field_name='timestamp', lookup_expr='lte')

    class Meta:
        model = ChainOfCustody
        fields = ['new_state', 'date_after', 'date_before']
