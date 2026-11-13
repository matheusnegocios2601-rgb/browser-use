"""Entrada do aplicativo.  python -m voznav            abre o app
                         python -m voznav --texto "abre o youtube"   mostra a decisão sem microfone e sem abrir nada"""

import argparse
import os
import sys
import time

T_INICIO = time.monotonic()


def main() -> None:
	# Aberto pelo pythonw (sem console), stdout/stderr são None e bibliotecas que escrevem neles quebram.
	for nome in ('stdout', 'stderr'):
		if getattr(sys, nome) is None:
			setattr(sys, nome, open(os.devnull, 'w', encoding='utf-8'))  # noqa: SIM115
	os.environ.setdefault('HF_HUB_DISABLE_PROGRESS_BARS', '1')
	os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
	ap = argparse.ArgumentParser(prog='voznav', description='Navegador pessoal por voz')
	ap.add_argument('--texto', help='interpreta uma frase escrita e mostra o que seria feito')
	ap.add_argument('--abrir', action='store_true', help='com --texto: abre de verdade no navegador padrão')
	args = ap.parse_args()
	if args.texto:
		from voznav.abrir import abrir_no_navegador
		from voznav.dados import Dados
		from voznav.sessao import Sessao

		d = Sessao(Dados()).processar(args.texto)
		print(f'{d.tipo}: {d.url or d.mensagem}  [{d.via}]')
		if args.abrir and d.tipo == 'abrir':
			abrir_no_navegador(d.url)
		return
	from voznav.interface import iniciar

	iniciar(T_INICIO)


if __name__ == '__main__':
	try:
		main()
	except Exception:
		import traceback
		from pathlib import Path

		# com pythonw não há console: deixa o erro num arquivo ao lado do app
		Path(__file__).resolve().parent.parent.joinpath('erro.log').write_text(traceback.format_exc(), encoding='utf-8')
		raise
