#!/bin/sh
# Entrypoint de produção do ForensiQ.
#
# O volume persistente do Fly (forensiq_media) é montado em runtime em
# /data/media e pertence a root:root. A app corre como utilizador não-root
# (forensiq) e precisa de escrever aqui os uploads de prova (fotos dos itens),
# por isso garantimos a propriedade no ARRANQUE — sobrevive a recriações do
# volume, ao contrário de um chown feito no build (que o mount sobrepõe).
set -e

if [ -d /data/media ]; then
    chown -R forensiq:forensiq /data/media 2>/dev/null || true
fi

# Largar privilégios: a aplicação corre como forensiq. gosu reexecuta como
# PID 1 preservando o encaminhamento de sinais (paragem graciosa do gunicorn).
exec gosu forensiq "$@"
