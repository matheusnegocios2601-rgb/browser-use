"""Normalização de texto.

Regra central do projeto: a *chave* (minúscula, sem acento, sem pontuação nas bordas) serve só para
reconhecer comandos; o texto *original* é o que segue para a consulta ou para o endereço.
"""

import re
import unicodedata
from dataclasses import dataclass

_BORDA = '.,!?;:…"“”‘’\'()[]¿¡'


def dobrar(s: str) -> str:
	"""Minúsculas e sem acentos. Mantém símbolos como + e # (C++, C#)."""
	s = unicodedata.normalize('NFD', s.lower())
	return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


@dataclass(frozen=True)
class Tok:
	orig: str
	chave: str


def tokens(texto: str) -> list[Tok]:
	texto = re.sub(r'\.{2,}|…', ' ', texto)
	saida: list[Tok] = []
	for bruto in texto.split():
		chave = dobrar(bruto).strip(_BORDA)
		if chave:
			saida.append(Tok(bruto.strip(_BORDA), chave))
	return saida


def chaves(texto: str) -> tuple[str, ...]:
	return tuple(t.chave for t in tokens(texto))


def chave_frase(texto: str) -> str:
	return ' '.join(chaves(texto))


def conteudo(toks: list[Tok]) -> str:
	"""Texto original de um trecho, sem a pontuação que o reconhecedor põe nas bordas da frase."""
	return ' '.join(t.orig for t in toks)


def distancia(a: str, b: str, limite: int = 2) -> int:
	"""Distância de edição com corte; devolve limite+1 quando passa do limite."""
	if abs(len(a) - len(b)) > limite:
		return limite + 1
	ant = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		atual = [i]
		for j, cb in enumerate(b, 1):
			atual.append(min(ant[j] + 1, atual[j - 1] + 1, ant[j - 1] + (ca != cb)))
		if min(atual) > limite:
			return limite + 1
		ant = atual
	return ant[-1]
