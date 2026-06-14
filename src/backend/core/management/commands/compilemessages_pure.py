"""
ForensiQ — Compilação de catálogos de tradução .po -> .mo em Python puro.

O `compilemessages` do Django invoca o `msgfmt` das GNU gettext-tools, que
não está disponível em todos os ambientes (nomeadamente Windows sem
MSYS2/choco). Este comando compila os ficheiros `.po` listados em
`settings.LOCALE_PATHS` sem dependências externas, produzindo `.mo` binários
que o Django lê em runtime. Suporta o subconjunto do formato `.po` que
usamos: cabeçalho, mensagens simples, mensagens com plural, continuação de
strings em múltiplas linhas e os escapes standard (\\n \\t \\r \\" \\\\).

O `.po` é a fonte de verdade (legível e versionada); o `.mo` é o artefacto
compilado — também versionado, para que nenhum ambiente (dev, CI,
produção/Fly) precise das gettext-tools.

Uso::

    python manage.py compilemessages_pure
    python manage.py compilemessages_pure --check   # não escreve; falha
                                                     # se algum .mo estiver
                                                     # desactualizado (CI)
"""

from __future__ import annotations

import array
import struct
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

MO_MAGIC = 0x950412DE
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\', '0': '\0'}


def _unescape(s: str) -> str:
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n:
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def _quoted(line: str) -> str:
    """Conteúdo entre as primeiras e últimas aspas duplas da linha."""
    a, b = line.find('"'), line.rfind('"')
    return line[a + 1:b] if a != -1 and b > a else ''


def parse_po(text: str) -> list[dict]:
    """Lê um `.po` para uma lista de entradas. As entradas são separadas
    por linhas em branco (estilo gerado pelo gettext)."""
    entries: list[dict] = []

    def blank():
        return {'msgid': None, 'msgid_plural': None, 'msgstr': None, 'plurals': {}}

    cur, last = blank(), None
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            if cur['msgid'] is not None:
                entries.append(cur)
            cur, last = blank(), None
            continue
        if s.startswith('#'):
            continue
        if s.startswith('msgid_plural'):
            cur['msgid_plural'] = _unescape(_quoted(s))
            last = 'mp'
        elif s.startswith('msgid'):
            cur['msgid'] = _unescape(_quoted(s))
            last = 'id'
        elif s.startswith('msgstr['):
            idx = int(s[s.find('[') + 1:s.find(']')])
            cur['plurals'][idx] = _unescape(_quoted(s))
            last = ('plural', idx)
        elif s.startswith('msgstr'):
            cur['msgstr'] = _unescape(_quoted(s))
            last = 'str'
        elif s.startswith('"'):  # continuação da string anterior
            frag = _unescape(_quoted(s))
            if last == 'id':
                cur['msgid'] += frag
            elif last == 'mp':
                cur['msgid_plural'] += frag
            elif last == 'str':
                cur['msgstr'] = (cur['msgstr'] or '') + frag
            elif isinstance(last, tuple):
                cur['plurals'][last[1]] += frag
    if cur['msgid'] is not None:
        entries.append(cur)
    return entries


def build_catalog(entries: list[dict]) -> dict[str, str]:
    """Converte entradas em {chave_mo: valor_mo} (chave/valor com plural
    codificados com NUL, como no formato GNU .mo)."""
    catalog: dict[str, str] = {}
    for e in entries:
        if e['msgid'] is None:
            continue
        if e['msgid_plural'] is not None:
            key = e['msgid'] + '\x00' + e['msgid_plural']
            n = (max(e['plurals']) + 1) if e['plurals'] else 0
            value = '\x00'.join(e['plurals'].get(i, '') for i in range(n))
        else:
            key = e['msgid']
            value = e['msgstr'] or ''
        # Saltar traduções vazias (exceto o cabeçalho, cuja chave é '').
        if key != '' and value == '':
            continue
        catalog[key] = value
    return catalog


def serialize_mo(catalog: dict[str, str]) -> bytes:
    """Serializa um catálogo para bytes no formato GNU .mo."""
    keys = sorted(catalog, key=lambda k: k.encode('utf-8'))
    offsets, ids, strs = [], b'', b''
    for k in keys:
        kb, vb = k.encode('utf-8'), catalog[k].encode('utf-8')
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b'\x00'
        strs += vb + b'\x00'
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets, voffsets = [], []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    out = struct.pack(
        'Iiiiiii', MO_MAGIC, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0
    )
    out += array.array('i', koffsets + voffsets).tobytes()
    return out + ids + strs


def compile_po(po_path: Path) -> bytes:
    return serialize_mo(build_catalog(parse_po(po_path.read_text(encoding='utf-8'))))


class Command(BaseCommand):
    help = (
        'Compila os .po em LOCALE_PATHS para .mo em Python puro (sem '
        'GNU gettext-tools). --check falha se algum .mo estiver '
        'desactualizado, sem escrever (uso em CI).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--check',
            action='store_true',
            help='Não escreve; falha se algum .mo estiver desactualizado.',
        )

    def handle(self, *args, **options):
        locale_paths = [Path(p) for p in getattr(settings, 'LOCALE_PATHS', [])]
        if not locale_paths:
            raise CommandError('settings.LOCALE_PATHS está vazio — nada a compilar.')

        po_files = sorted(
            {po for lp in locale_paths if lp.exists() for po in lp.rglob('*.po')}
        )
        if not po_files:
            self.stdout.write(self.style.WARNING('Nenhum .po encontrado em LOCALE_PATHS.'))
            return

        check = options['check']
        stale = []
        for po in po_files:
            data = compile_po(po)
            mo = po.with_suffix('.mo')
            if check:
                if not mo.exists() or mo.read_bytes() != data:
                    stale.append(mo)
                continue
            mo.write_bytes(data)
            self.stdout.write(self.style.SUCCESS(f'  {po.name} -> {mo.name}'))

        if check:
            if stale:
                nomes = ', '.join(str(s) for s in stale)
                raise CommandError(
                    f'.mo desactualizado(s) face ao .po: {nomes}. '
                    'Corre `python manage.py compilemessages_pure`.'
                )
            self.stdout.write(self.style.SUCCESS('Catálogos .mo estão sincronizados.'))
