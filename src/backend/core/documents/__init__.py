"""
ForensiQ — Geração de documentos PDF.

``core.documents`` separa a CASCA reutilizável (``chrome`` — cabeçalho/rodapé/logo;
``builder.DocumentBuilder`` — estilos e blocos que se adaptam aos campos) do
CONTEÚDO de cada documento (``guia_transporte``). Qualquer documento futuro
compõe-se sobre o mesmo ``DocumentBuilder``, sem recriar a casca.

API pública:
- :func:`generate_guia_transporte` — guia de transporte (PDF) de uma remessa.
"""

from core.documents.guia_transporte import generate_guia_transporte

__all__ = ['generate_guia_transporte']
