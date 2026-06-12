"""ForensiQ — filtros de template do gerador de grelhas (fonte única).

``cellattr`` resolve um nome de atributo VARIÁVEL em runtime — o que o Django
``{{ row.<var> }}`` não permite (o campo de cada coluna vem da spec
``GridColumn.key``, só conhecido em execução). Suporta caminhos com ponto
(``evidence.code``) e cai para acesso por chave em mapeamentos. Devolve o valor
CRU (para encadear ``|date``/``|default``/``|default_if_none``) e ``''`` quando
não existe, sem INVOCAR callables (os rótulos são pré-computados no decorate da
view — coerente com ``type_label``/``state_badge`` e evita chamadas acidentais).
"""
from django import template

register = template.Library()


@register.filter
def cellattr(row, key):
    """Valor da célula em ``row`` para o atributo ``key`` (caminho com ponto)."""
    value = row
    for part in str(key).split('.'):
        if value is None:
            return ''
        try:
            value = getattr(value, part)
        except (AttributeError, TypeError):
            try:
                value = value[part]
            except (TypeError, KeyError, IndexError):
                return ''
    return value


@register.filter
def human_hours(value):
    """Duração humana a partir de HORAS decimais (fonte única).

    Até 48h mantém as horas tal como vêm de ``core.analytics`` (437.2 →
    ``437.2h`` deixava de se ler; 10.5 → ``10.5h``); acima disso lê-se em dias
    (``18 d``). Só para durações DECORRIDAS — as constantes legais (72h) e o
    prazo de calendário da perícia têm semântica própria e não passam por aqui.
    """
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return ''
    if hours > 48:
        return f'{round(hours / 24)} d'
    return f'{value}h'
