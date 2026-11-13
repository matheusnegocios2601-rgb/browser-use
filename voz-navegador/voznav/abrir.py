"""Entrega a URL ao navegador padrão. Nada de shell: no Windows é o ShellExecute via os.startfile."""

import os
import sys
import webbrowser

from voznav.urls import validar_url


def abrir_no_navegador(url: str) -> None:
	url = validar_url(url)  # última barreira: só http(s) chega ao sistema
	if sys.platform == 'win32':
		os.startfile(url)  # noqa: S606 - usa o navegador e o perfil padrão do usuário, sem depuração remota
	else:
		webbrowser.open(url)
