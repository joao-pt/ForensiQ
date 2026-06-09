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
