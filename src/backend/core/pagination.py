"""Paginação DRF com cap defensivo.

``page_size_query_param`` permite ao cliente pedir 20/50/100 itens — útil
para o modo tabela densa (50 default em desktop) e cards (20 default em
mobile). ``max_page_size`` corta pedidos abusivos: pedir
``?page_size=100000`` é rejeitado para o valor cap.
"""

from rest_framework.pagination import PageNumberPagination


class BoundedPageNumberPagination(PageNumberPagination):
    """Pagination class usada como default em todos os endpoints DRF.

    Mantém compatibilidade com o ``DEFAULT_PAGINATION_CLASS`` anterior
    (``PageNumberPagination``) — só acrescenta o cap e o query param.
    """

    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100
