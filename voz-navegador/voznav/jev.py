"""Integração OPCIONAL com o Jev (TypeSafe AI): desempate entre atalhos quando as regras locais ficam em dúvida.

O Jev é um classificador em nuvem (70-500 ms por chamada, segundo a TypeSafe). Ele NÃO acelera o caminho
comum: abrir favorito, pesquisar e endereço ditado são resolvidos localmente em ~1 ms e nunca passam por aqui.
Só é consultado quando a alternativa seria perguntar "qual dos dois?" ou não achar nada para uma descrição
longa. Fica desligado por padrão; ligado, envia à TypeSafe a frase dita e nome/descrição/domínio dos atalhos
candidatos (nunca a URL completa, áudio ou histórico).
"""

import json
import os
import urllib.request
from urllib.parse import urlsplit

from voznav.dados import Config, Entrada

URL_API = 'https://api.typesafe.ai/v1/systemone'


class Jev:
	def __init__(self, chave: str, url: str = URL_API, limite_s: float = 1.5, modelo: str = 'jev-latest'):
		self.chave, self.url, self.limite_s, self.modelo = chave, url, limite_s, modelo
		self.ultimo_erro = ''

	def escolher(self, frase: str, candidatos: list[Entrada]) -> Entrada | None:
		"""Devolve um candidato só se a resposta for folgada; qualquer dúvida, erro ou demora devolve None."""
		opcoes = {f'op{i + 1}': e for i, e in enumerate(candidatos[:40])}
		criterios = {k: ' — '.join(p for p in (e.nome, ', '.join(e.apelidos), e.descricao, urlsplit(e.url).hostname or '') if p) for k, e in opcoes.items()}
		# O Jev sempre escolhe alguma opção; sem esta saída explícita ele forçaria um atalho mesmo sem evidência.
		criterios['nenhum'] = 'Nenhum atalho corresponde claramente ao que foi dito, ou mais de um é igualmente plausível'
		corpo = {
			'model': self.modelo,
			'state': f'Pedido falado a um navegador por voz, em português do Brasil: "{frase}"',
			'questions': {'destino': {'type': 'choice', 'instructions': 'Qual atalho salvo o usuário quer abrir', 'criteria': criterios}},
		}
		pedido = urllib.request.Request(
			self.url, data=json.dumps(corpo).encode('utf-8'), method='POST',
			headers={'Authorization': f'Bearer {self.chave}', 'Content-Type': 'application/json'},
		)
		try:
			with urllib.request.urlopen(pedido, timeout=self.limite_s) as resposta:  # noqa: S310 - URL fixa https
				destino = json.loads(resposta.read().decode('utf-8'))['answers']['destino']
			escolha = destino['choice']
			probs = sorted((float(v) for v in destino.get('probabilities', {}).values()), reverse=True)
			confianca = float(destino.get('confidence', 0.0))
		except Exception as erro:  # rede, tempo esgotado, formato inesperado: segue o fluxo local
			self.ultimo_erro = str(erro)
			return None
		# A confiança do Jev não é tratada como probabilidade calibrada para o nosso uso: exige-se também
		# probabilidade alta da opção e folga grande sobre a segunda colocada.
		folga = probs[0] - probs[1] if len(probs) > 1 else probs[0] if probs else 0.0
		if escolha in opcoes and confianca >= 0.75 and probs and probs[0] >= 0.7 and folga >= 0.35:
			return opcoes[escolha]
		return None


def criar_desempate(config: Config):
	chave = os.environ.get('TYPESAFE_API_KEY') or config.jev_chave
	if not (config.jev_ativo and chave):
		return None
	return Jev(chave).escolher
