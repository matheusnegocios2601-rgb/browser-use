"""Decide o que fazer com cada frase: abrir, perguntar, pedir para repetir. Guarda o diálogo pendente."""

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from voznav.dados import Dados, Entrada
from voznav.pedido import Pedido, analisar
from voznav.texto import Tok, chave_frase, chaves, conteudo, tokens
from voznav.urls import completar_url, endereco_falado, montar_busca

_POSSE = {'meu', 'minha', 'meus', 'minhas', 'o', 'a', 'os', 'as'}
_VAZIAS = _POSSE | {
	'de', 'do', 'da', 'dos', 'das', 'que', 'eu', 'pra', 'para', 'aquela', 'aquele', 'aquilo', 'pagina', 'site', 'salvei', 'salvo', 'salva',
	'um', 'uma', 'e', 'com', 'no', 'na', 'em', 'la', 'coisa', 'negocio', 'link', 'atalho', 'onde', 'fica', 'tem', 'por', 'ver',
}


@dataclass
class Decisao:
	tipo: str  # 'abrir' | 'escolher' | 'repetir' | 'dialogo' | 'pausar' | 'cancelado' | 'config' | 'ignorar'
	url: str = ''
	rotulo: str = ''
	mensagem: str = ''
	opcoes: list[tuple[str, str]] = field(default_factory=list)
	via: str = ''
	extensivel: bool = False  # vale esperar um pouco: a frase pode continuar ("YouTube... Music")
	oferta: str = ''


@dataclass
class _Pendente:
	tipo: str  # 'escolha' | 'criar_nome' | 'criar_url' | 'criar_confirma' | 'apelido'
	opcoes: list[tuple[str, str]] = field(default_factory=list)
	nome: str = ''
	url: str = ''
	entrada: Entrada | None = None
	frase: str = ''


def _radical(p: str) -> str:
	return p[:5] if len(p) > 5 else p.rstrip('s') if len(p) > 3 else p


def _parecidas(a: str, b: str) -> bool:
	return _radical(a) == _radical(b) or (len(a) > 4 and SequenceMatcher(None, a, b).ratio() >= 0.84)


def _sem_posse(ch: tuple[str, ...]) -> tuple[str, ...]:
	while len(ch) > 1 and ch[0] in _POSSE:
		ch = ch[1:]
	return ch


class Sessao:
	"""Uma sessão de uso. `processar(frase)` devolve a decisão; quem chama é que abre a URL."""

	def __init__(self, dados: Dados, desempate: Callable[[str, list[Entrada]], Entrada | None] | None = None, agora: Callable[[], float] = time.monotonic):
		self.dados = dados
		self.desempate = desempate
		self.agora = agora
		self.pendente: _Pendente | None = None
		self._falha: tuple[str, str, float] | None = None  # (frase original, chave, instante)
		self._correcoes: dict[tuple[str, str], int] = {}
		self._recusados: set[tuple[str, str]] = set()

	# --- API para a interface ------------------------------------------------------------------------

	@property
	def aguardando(self) -> bool:
		return self.pendente is not None

	def cancelar(self) -> Decisao:
		tinha = self.pendente is not None
		self.pendente = None
		return Decisao('cancelado', mensagem='Cancelado.' if tinha else 'Nada para cancelar.')

	def informar_endereco(self, texto: str) -> Decisao:
		"""Endereço digitado ou colado durante a criação de um atalho."""
		p = self.pendente
		if not p or p.tipo not in ('criar_url', 'criar_confirma'):
			return Decisao('repetir', mensagem='Nenhum atalho sendo criado.')
		try:
			p.url = completar_url(texto)
		except ValueError as erro:
			return Decisao('dialogo', mensagem=f'{erro} Dite ou cole o endereço de novo.')
		p.tipo = 'criar_confirma'
		return self._confirmacao(p)

	def confirmar_atalho(self, nome: str, url: str) -> Decisao:
		"""Salva com os valores (possivelmente corrigidos à mão) mostrados na tela de confirmação."""
		try:
			atalho = self.dados.gravar_atalho(nome, completar_url(url))
		except ValueError as erro:
			return Decisao('dialogo', mensagem=str(erro))
		self.pendente = None
		return Decisao('dialogo', mensagem=f'Atalho "{atalho.nome}" salvo. Diga "abre {atalho.nome}".', via='atalho_salvo')

	def instantaneo(self) -> tuple:
		"""Estado do diálogo, para o motor desfazer uma decisão que acabou não valendo (a frase continuou)."""
		return (copy.copy(self.pendente), self._falha, dict(self._correcoes))

	def restaurar(self, estado: tuple) -> None:
		self.pendente, self._falha, self._correcoes = estado[0], estado[1], dict(estado[2])

	# --- entrada principal ---------------------------------------------------------------------------

	def processar(self, texto: str) -> Decisao:
		nomes_busca = {chaves(n) for e in self.dados.todos_servicos() if e.busca for n in e.nomes()}
		em_dialogo = self.pendente is not None and self.pendente.tipo != 'escolha'
		pedido = analisar(texto, nomes_busca, em_dialogo=em_dialogo)
		if pedido.tipo == 'vazio':
			return Decisao('repetir', mensagem='Não entendi. Pode repetir?')
		if pedido.tipo == 'controle' and pedido.controle == 'pausar':
			self.pendente = None
			return Decisao('pausar', mensagem='Escuta pausada.')
		if pedido.tipo == 'controle' and pedido.controle == 'cancelar':
			return self.cancelar()
		if self.pendente:
			resposta = self._responder_pendente(pedido, texto)
			if resposta:
				return resposta
		if pedido.tipo == 'controle':
			return self._controle(pedido)
		if pedido.tipo == 'buscar':
			return self._buscar(pedido)
		return self._abrir(pedido)

	# --- diálogos ------------------------------------------------------------------------------------

	def _responder_pendente(self, pedido: Pedido, texto: str) -> Decisao | None:
		p = self.pendente
		assert p is not None
		if p.tipo == 'escolha':
			indice = None
			if pedido.tipo == 'controle' and pedido.controle == 'ordinal':
				indice = int(pedido.arg) - 1
			else:
				dito = set(_sem_posse(chaves(texto)))
				achados = [i for i, (rotulo, _) in enumerate(p.opcoes) if dito and dito <= set(chaves(rotulo))]
				indice = achados[0] if len(achados) == 1 else None
			if indice is not None and 0 <= indice < len(p.opcoes):
				rotulo, url = p.opcoes[indice]
				self.pendente = None
				return self._abriu(Decisao('abrir', url=url, rotulo=rotulo, via='escolha'), rotulo)
			if pedido.tipo == 'controle' and pedido.controle == 'ordinal':
				return Decisao('escolher', opcoes=p.opcoes, mensagem=f'Só há {len(p.opcoes)} opções. ' + self._pergunta(p.opcoes))
			if pedido.tipo in ('abrir', 'buscar') and (pedido.verbo or len(pedido.alvo) > 0) and self._parece_comando(pedido):
				self.pendente = None  # um comando novo e claro substitui a pergunta
				return None
			return Decisao('escolher', opcoes=p.opcoes, mensagem=self._pergunta(p.opcoes))

		if p.tipo == 'apelido':
			self.pendente = None
			if pedido.tipo == 'controle' and pedido.controle in ('sim', 'salvar') and p.entrada:
				self.dados.acrescentar_apelido(p.entrada, p.frase)
				return Decisao('dialogo', mensagem=f'Pronto: "{p.frase}" agora abre {p.entrada.nome}.', via='apelido_salvo')
			self._recusados.add((chave_frase(p.frase), p.entrada.nome if p.entrada else ''))
			if pedido.tipo == 'controle' and pedido.controle == 'nao':
				return Decisao('dialogo', mensagem='Tudo bem, não salvei.')
			return None  # qualquer outra coisa é um comando normal

		if p.tipo == 'criar_nome':
			if pedido.tipo == 'controle':
				return Decisao('dialogo', mensagem='Qual é o nome do atalho?')
			p.nome, p.tipo = conteudo(tokens(texto)), 'criar_url'
			return Decisao('dialogo', mensagem=f'Atalho "{p.nome}". Dite o endereço ou cole na janela.')

		if p.tipo == 'criar_url':
			url = endereco_falado(tokens(texto))
			if not url:
				bruto = texto.strip()
				if ' ' not in bruto and '.' in bruto:
					return self.informar_endereco(bruto)
				return Decisao('dialogo', mensagem='Não entendi o endereço. Dite de novo (ex.: "exemplo ponto com barra painel") ou cole na janela.')
			p.url, p.tipo = url, 'criar_confirma'
			return self._confirmacao(p)

		if p.tipo == 'criar_confirma':
			if pedido.tipo == 'controle' and pedido.controle in ('salvar', 'sim'):
				return self.confirmar_atalho(p.nome, p.url)
			if pedido.tipo == 'controle' and pedido.controle == 'corrigir_nome' and pedido.arg:
				p.nome = pedido.arg
				return self._confirmacao(p)
			if pedido.tipo == 'controle' and pedido.controle in ('corrigir_endereco', 'nao', 'corrigir_nome'):
				if pedido.controle == 'corrigir_nome':
					p.tipo = 'criar_nome'
					return Decisao('dialogo', mensagem='Qual é o nome certo?')
				p.tipo = 'criar_url'
				return Decisao('dialogo', mensagem='Dite o endereço de novo ou cole na janela.')
			url = endereco_falado(tokens(texto))
			if url:
				p.url = url
			return self._confirmacao(p)
		return None

	def _parece_comando(self, pedido: Pedido) -> bool:
		if pedido.tipo == 'buscar':
			return bool(pedido.consulta)
		return pedido.verbo or bool(self._exatos(tuple(t.chave for t in pedido.alvo)))

	def _confirmacao(self, p: _Pendente) -> Decisao:
		existente = self.dados.achar_atalho(p.nome)
		aviso = f' Isso substitui o destino atual de "{existente.nome}": {existente.url}.' if existente and existente.url != p.url else ''
		return Decisao('dialogo', mensagem=f'Salvar "{p.nome}" → {p.url} ?{aviso} Diga "salvar" ou "cancelar".', rotulo=p.nome, url=p.url, via='confirmar_atalho')

	@staticmethod
	def _pergunta(opcoes: list[tuple[str, str]]) -> str:
		ordem = ['primeiro', 'segundo', 'terceiro']
		itens = '  '.join(f'{i + 1}) {rotulo}' for i, (rotulo, _) in enumerate(opcoes))
		return f'Qual? {itens}  — diga "o {ordem[0]}", "o {ordem[1]}" ou "cancelar".'

	def _controle(self, pedido: Pedido) -> Decisao:
		if pedido.controle == 'criar_atalho':
			if pedido.arg:
				self.pendente = _Pendente('criar_url', nome=pedido.arg)
				return Decisao('dialogo', mensagem=f'Atalho "{pedido.arg}". Dite o endereço ou cole na janela.', via='criar_atalho')
			self.pendente = _Pendente('criar_nome')
			return Decisao('dialogo', mensagem='Qual é o nome do atalho?', via='criar_atalho')
		if pedido.controle == 'config':
			return Decisao('config', mensagem='Abrindo as configurações.')
		return Decisao('repetir', mensagem='Não há nada aguardando resposta. Diga "abre…" ou "pesquisa…".')

	# --- busca ---------------------------------------------------------------------------------------

	def _texto_consulta(self, toks: list[Tok]) -> str:
		"""Texto original da consulta, com as pronúncias cadastradas trocadas pela escrita ("c mais mais" -> "C++")."""
		mapa = {chaves(fala): escrita for fala, escrita in self.dados.config.pronuncias.items()}
		saida: list[str] = []
		i = 0
		while i < len(toks):
			for n in range(min(4, len(toks) - i), 0, -1):
				escrita = mapa.get(tuple(t.chave for t in toks[i : i + n]))
				if escrita:
					saida.append(escrita)
					i += n
					break
			else:
				saida.append(toks[i].orig)
				i += 1
		return ' '.join(saida)

	def _buscar(self, pedido: Pedido) -> Decisao:
		if pedido.pendurado:
			return Decisao('repetir', mensagem='Pesquisar o quê?', extensivel=True)
		consulta = self._texto_consulta(pedido.consulta)
		if pedido.servico:
			alvo = tuple(t.chave for t in pedido.servico)
			servico = next(e for e in self.dados.todos_servicos() if e.busca and alvo in {chaves(n) for n in e.nomes()})
			assert servico.busca
			return Decisao('abrir', url=montar_busca(servico.busca, consulta), rotulo=f'{servico.nome}: {consulta}', via='busca_servico')
		return Decisao('abrir', url=montar_busca(self.dados.config.buscador, consulta), rotulo=f'Pesquisa: {consulta}', via='busca')

	# --- abrir ---------------------------------------------------------------------------------------

	def _exatos(self, alvo: tuple[str, ...]) -> list[Entrada]:
		"""Entradas cujo nome ou apelido é exatamente o alvo (com ou sem "meu"/"o" na frente)."""
		for variante in (alvo, _sem_posse(alvo)):
			achados = [e for e in self.dados.catalogo() if any(variante in (chaves(n), _sem_posse(chaves(n))) for n in e.nomes())]
			if achados:
				pessoais = [e for e in achados if e.pessoal]
				return pessoais or achados
		return []

	def _pontuar(self, alvo: tuple[str, ...], e: Entrada) -> float:
		"""Quanto a frase descreve a entrada: cobertura das palavras da frase (peso menor se só a descrição bate) e do nome."""
		palavras = [p for p in alvo if p not in _VAZIAS]
		if not palavras:
			return 0.0
		do_nome = [p for n in e.nomes() for p in chaves(n) if p not in _VAZIAS]
		da_descricao = [p for p in chaves(e.descricao) if p not in _VAZIAS]
		total = 0.0
		for p in palavras:
			if any(_parecidas(p, q) for q in do_nome):
				total += 1.0
			elif any(_parecidas(p, q) for q in da_descricao):
				total += 0.7
		cobertura_frase = total / len(palavras)
		principais = [p for p in chaves(e.nome) if p not in _VAZIAS] or list(chaves(e.nome))
		cobertura_nome = sum(any(_parecidas(p, q) for q in palavras) for p in principais) / len(principais)
		return 0.8 * cobertura_frase + 0.2 * cobertura_nome

	def _palavras_em_comum(self, alvo: tuple[str, ...], e: Entrada) -> int:
		dele = [p for texto in (*e.nomes(), e.descricao) for p in chaves(texto) if p not in _VAZIAS]
		return sum(any(_parecidas(p, q) for q in dele) for p in {p for p in alvo if p not in _VAZIAS})

	def _abrir(self, pedido: Pedido) -> Decisao:
		if not pedido.alvo:
			return Decisao('repetir', mensagem='Abrir o quê?', extensivel=True)
		alvo = tuple(t.chave for t in pedido.alvo)
		frase = conteudo(pedido.alvo)

		url = endereco_falado(pedido.alvo)
		if url:
			return Decisao('abrir', url=url, rotulo=url, via='endereco')

		exatos = self._exatos(alvo)
		if not exatos and not pedido.verbo and len(alvo) >= 2 and self._exatos(alvo[1:]):
			# "Abreu YouTube", "Abia Netflix": a primeira palavra é o verbo que o reconhecedor estragou; o nome está intacto.
			alvo = alvo[1:]
			exatos = self._exatos(alvo)
		if len(exatos) == 1:
			return self._abriu(Decisao('abrir', url=exatos[0].url, rotulo=exatos[0].nome, via='nome', extensivel=self._pode_continuar(alvo)), exatos[0].nome, exatos[0])
		if len(exatos) > 1:
			return self._perguntar(exatos[:3])

		# Sem nome exato: compara com nomes, apelidos e descrições dos atalhos pessoais. A pontuação não é
		# probabilidade; o que decide é passar do piso E ter folga sobre o segundo colocado.
		notas = sorted(((self._pontuar(alvo, e), e) for e in self.dados.atalhos), key=lambda par: -par[0])
		bons = [(nota, e) for nota, e in notas if nota >= 0.5 or (nota >= 0.25 and self._palavras_em_comum(alvo, e) >= 2)]
		if bons and (len(bons) == 1 or bons[0][0] - bons[1][0] >= 0.2):
			e = bons[0][1]
			return self._abriu(Decisao('abrir', url=e.url, rotulo=e.nome, via='descricao'), e.nome, e)
		if len(bons) > 1:
			empatados = [e for nota, e in bons if bons[0][0] - nota < 0.2][:3]
			escolhido = self.desempate(frase, empatados) if self.desempate else None
			if escolhido:
				return self._abriu(Decisao('abrir', url=escolhido.url, rotulo=escolhido.nome, via='jev'), escolhido.nome, escolhido)
			return self._perguntar(empatados)

		# Nome de serviço com erro de reconhecimento ("netiflix"): só aceita se for claramente um só.
		junto = ''.join(_sem_posse(alvo))
		proximos = sorted(((max(SequenceMatcher(None, junto, ''.join(chaves(n))).ratio() for n in e.nomes()), e) for e in self.dados.catalogo()), key=lambda par: -par[0])
		if len(junto) >= 5 and proximos and proximos[0][0] >= 0.86 and (len(proximos) == 1 or proximos[0][0] - proximos[1][0] >= 0.08):
			e = proximos[0][1]
			return self._abriu(Decisao('abrir', url=e.url, rotulo=e.nome, via='nome_aproximado'), e.nome, e)
		# "noupainel": o nome inteiro está lá, com até 3 letras grudadas na frente.
		colados = [e for e in self.dados.catalogo() if any(len(c) >= 5 and junto.endswith(c) and len(junto) - len(c) <= 3 for c in (''.join(chaves(n)) for n in e.nomes()))]
		if len(colados) == 1:
			return self._abriu(Decisao('abrir', url=colados[0].url, rotulo=colados[0].nome, via='nome_aproximado'), colados[0].nome, colados[0])

		if self.desempate and len(junto) >= 4:
			# Nada reconhecido pelas regras locais: antes de pedir para repetir, pergunta ao Jev (se ligado) qual
			# atalho ou serviço a frase quer dizer. Ele tem a opção "nenhum" e só vale com folga.
			escolhido = self.desempate(frase, self.dados.catalogo()[:120])
			if escolhido:
				return self._abriu(Decisao('abrir', url=escolhido.url, rotulo=escolhido.nome, via='jev'), escolhido.nome, escolhido)

		self._falha = (frase, ' '.join(alvo), self.agora())
		if pedido.verbo or pedido.site:
			# Destino desconhecido: pesquisa o nome em vez de inventar um domínio.
			# 'busca_site': a pessoa pediu explicitamente "o site de X"; 'busca_nome': só não reconheci o nome.
			return Decisao('abrir', url=montar_busca(self.dados.config.buscador, frase), rotulo=f'Pesquisa: {frase}', via='busca_site' if pedido.site else 'busca_nome')
		return Decisao('repetir', mensagem=f'Não reconheci "{frase}". Diga "abre…" ou "pesquisa…".')

	def _perguntar(self, entradas: list[Entrada]) -> Decisao:
		opcoes = [(e.nome, e.url) for e in entradas]
		self.pendente = _Pendente('escolha', opcoes=opcoes)
		return Decisao('escolher', opcoes=opcoes, mensagem=self._pergunta(opcoes))

	def _pode_continuar(self, alvo: tuple[str, ...]) -> bool:
		"""O alvo é o começo de outro nome conhecido? ("youtube" -> "youtube music")"""
		base = _sem_posse(alvo)
		for e in self.dados.catalogo():
			for n in e.nomes():
				outro = _sem_posse(chaves(n))
				if len(outro) > len(base) and outro[: len(base)] == base:
					return True
		return False

	def _abriu(self, decisao: Decisao, nome: str, entrada: Entrada | None = None) -> Decisao:
		"""Depois de um acerto, vê se o usuário acabou de corrigir a mesma pronúncia pela segunda vez."""
		falha, self._falha = self._falha, None
		if not falha or not entrada or self.agora() - falha[2] > 45:
			return decisao
		par = (falha[1], nome)
		if par in self._recusados or falha[1] in {chave_frase(n) for n in entrada.nomes()}:
			return decisao
		self._correcoes[par] = self._correcoes.get(par, 0) + 1
		if self._correcoes[par] >= 2:
			self.pendente = _Pendente('apelido', entrada=entrada, frase=falha[0])
			decisao.oferta = f'Você disse "{falha[0]}" e depois abriu {nome} mais de uma vez. Salvar "{falha[0]}" como apelido? Diga "sim" ou "não".'
		return decisao
