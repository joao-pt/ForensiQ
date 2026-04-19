"""Redirect externo para VIN decoder — ver ADR-0010.

Decisão arquitectural: **sem scraping** de vindecoder.eu nem integração
com APIs comerciais de VIN decode. O agente abre o URL numa nova aba,
confirma visualmente os dados e preenche o formulário do ForensiQ à mão.

Trade-offs:
- Zero dependência dura de um terceiro (sem risco de rate-limit, preço
  ou TOS).
- Confirmação visual pelo perito reforça a cadeia de custódia (o agente
  declara ter visto e confirmado cada campo).
- Zero PII enviada para APIs externas pelo backend — o VIN só é
  conhecido pelo browser do agente.
"""

from __future__ import annotations

_VINDECODER_BASE = 'https://vindecoder.eu/check-vin'


def build_vindecoder_url(vin: str) -> str:
    """Constrói o URL público de vindecoder.eu para um VIN.

    Args:
        vin: string com 17 caracteres (já validada pelo caller via
            ``core.validators.validate_vin``).

    Returns:
        URL absoluto para o agente abrir numa nova aba. Não faz I/O.
    """
    return f'{_VINDECODER_BASE}/{vin.strip().upper()}'
