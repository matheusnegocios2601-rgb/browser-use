"""Da frase reconhecida para um pedido estruturado. Só regras locais: nenhuma chamada de rede."""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from voznav.texto import Tok, conteudo, distancia, tokens

BUSCAR = {'pesquisa', 'pesquisar', 'pesquise', 'procura', 'procurar', 'procure', 'busca', 'buscar', 'busque'}
ABRIR = {
	'abre', 'abrir', 'abra', 'abri', 'vai', 'va', 'ir', 'vamos', 'entra', 'entrar', 'entre', 'acessa', 'acessar', 'acesse',
	'navega', 'navegar', 'navegue', 'mostra', 'mostrar', 'mostre', 'bota', 'coloca', 'carrega', 'visita', 'visitar', 'leva', 'levar',
}
MODAIS = {'quero', 'queria', 'pode', 'poderia', 'consegue', 'me', 'eu', 'bora', 'preciso', 'gostaria', 'de'}
CONECTORES = {'pro', 'pra', 'para', 'no', 'na', 'em', 'o', 'a', 'os', 'as', 'ao', 'ate', 'um', 'uma', 'do', 'da', 'de', 'aquele', 'aquela'}
EM_SERVICO = {'no', 'na', 'em', 'pelo', 'pela'}
SITE = {'site', 'pagina', 'portal'}

_INICIO = [('por', 'favor'), ('por', 'gentileza'), ('ei',), ('oi',), ('ola',), ('olha',), ('entao',), ('bom',), ('ok',), ('agora',), ('computador',), ('navegador',)]
_FIM = [('por', 'favor'), ('por', 'gentileza'), ('pra', 'mim'), ('para', 'mim'), ('agora',), ('rapidinho',), ('valeu',), ('obrigado',), ('obrigada',)]
# Só são muleta quando vêm acentuados: "abre a Open AI" não pode perder o "AI".
_MULETAS_ACENTUADAS = {'aí', 'lá', 'tá'}

_CONTROLES = {
	'cancelar': ['cancelar', 'cancela', 'cancele', 'deixa pra la', 'deixa para la', 'esquece', 'esqueca', 'deixa quieto', 'nenhum', 'nenhuma', 'nenhum dos dois'],
	'pausar': [
		'pausar escuta', 'pausa escuta', 'pausar a escuta', 'pausa a escuta', 'pause a escuta', 'pausar', 'para de ouvir', 'parar de ouvir',
		'pare de ouvir', 'para de escutar', 'parar escuta', 'desligar microfone', 'desliga o microfone', 'pausar a escuta do microfone',
	],
	'salvar': ['salvar', 'salva', 'salve', 'pode salvar', 'confirmar', 'confirma', 'confirmo'],
	'sim': ['sim', 'isso', 'pode', 'quero', 'aceito', 'pode sim', 'sim pode', 'isso mesmo'],
	'nao': ['nao', 'nao quero', 'nao precisa', 'agora nao'],
	'config': ['configuracoes', 'abrir configuracoes', 'abre as configuracoes', 'abrir as configuracoes', 'meus atalhos', 'abrir atalhos'],
}
_CONTROLE_POR_FRASE = {frase: acao for acao, frases in _CONTROLES.items() for frase in frases}
_ORDINAL = re.compile(r'^(?:o |a |opcao |numero |a opcao |o numero )?(primeir[oa]|um|uma|1|segund[oa]|dois|duas|2|terceir[oa]|tres|3)$')
_ORDEM = {'primeiro': 1, 'primeira': 1, 'um': 1, 'uma': 1, '1': 1, 'segundo': 2, 'segunda': 2, 'dois': 2, 'duas': 2, '2': 2, 'terceiro': 3, 'terceira': 3, 'tres': 3, '3': 3}
_CRIAR = re.compile(r'^(?:cria|criar|crie|novo|adiciona|adicionar|adicione|salva|salvar|salve|cadastra|cadastrar)(?: um| o)?(?: novo)? atalho(?: chamado| para| pra| de nome| com o nome)?(?: (.+))?$')
_CORRIGIR = re.compile(r'^(?:(?:corrigir|corrige|corrija|trocar|troca|mudar|muda) (?:o |a )?|o |a )?(nome|endereco|url)(?: para| pra| e| esta errado| errado)?(?: (.+))?$')


@dataclass
class Pedido:
	tipo: str  # 'abrir' | 'buscar' | 'controle' | 'vazio'
	alvo: list[Tok] = field(default_factory=list)
	consulta: list[Tok] = field(default_factory=list)
	servico: list[Tok] = field(default_factory=list)
	verbo: bool = False
	site: bool = False
	controle: str = ''
	arg: str = ''
	pendurado: bool = False  # termina em verbo ou conector: a frase provavelmente continua


def _aparar(toks: list[Tok]) -> list[Tok]:
	mudou = True
	while mudou and toks:
		mudou = False
		ch = [t.chave for t in toks]
		for frase in _INICIO:
			if len(toks) > len(frase) and tuple(ch[: len(frase)]) == frase:
				toks, mudou = toks[len(frase) :], True
				break
		else:
			for frase in _FIM:
				if len(toks) > len(frase) and tuple(ch[-len(frase) :]) == frase:
					toks, mudou = toks[: -len(frase)], True
					break
			else:
				if len(toks) > 1 and toks[-1].orig.lower() in _MULETAS_ACENTUADAS:
					toks, mudou = toks[:-1], True
				elif len(toks) > 1 and toks[0].orig.lower() in _MULETAS_ACENTUADAS:
					toks, mudou = toks[1:], True
	return toks


def _e_verbo_busca(chave: str) -> bool:
	# O reconhecedor às vezes troca letras do verbo ("esquisa", "desquiso"); tolera 1 ou 2 erros em palavra longa.
	erros = 2 if len(chave) >= 8 else 1
	return chave in BUSCAR or (len(chave) >= 6 and any(distancia(chave, v, erros) <= erros for v in ('pesquisa', 'pesquisar', 'procura', 'procurar')))


def _controle(toks: list[Tok], em_dialogo: bool) -> Pedido | None:
	frase = ' '.join(t.chave for t in toks)
	acao = _CONTROLE_POR_FRASE.get(frase)
	if not acao and 7 <= len(frase) <= 24:
		# "cancellar", "posar escuta": o reconhecedor erra uma letra; um comando de controle não pode se perder por isso.
		nota, parecido = max((SequenceMatcher(None, frase, f).ratio(), f) for f in _CONTROLE_POR_FRASE if len(f) >= 7)
		acao = _CONTROLE_POR_FRASE[parecido] if nota >= 0.88 else None
	# "sim", "salvar" e correções só são comandos enquanto há uma pergunta aberta.
	if acao and (em_dialogo or acao in ('cancelar', 'pausar', 'config')):
		return Pedido('controle', controle=acao)
	m = _ORDINAL.match(frase)
	if m:
		return Pedido('controle', controle='ordinal', arg=str(_ORDEM[m.group(1)]))
	m = _CRIAR.match(frase)
	if m:
		n = len(m.group(1).split()) if m.group(1) else 0
		return Pedido('controle', controle='criar_atalho', arg=conteudo(toks[len(toks) - n :]) if n else '')
	m = _CORRIGIR.match(frase) if em_dialogo else None
	if m:
		n = len(m.group(2).split()) if m.group(2) else 0
		campo = 'nome' if m.group(1) == 'nome' else 'endereco'
		return Pedido('controle', controle='corrigir_' + campo, arg=conteudo(toks[len(toks) - n :]) if n else '')
	return None


def _maior_nome(ch: list[str], inicio: int, nomes: set[tuple[str, ...]]) -> int:
	"""Tamanho do maior nome conhecido que começa em `inicio` (0 se nenhum)."""
	for fim in range(len(ch), inicio, -1):
		if tuple(ch[inicio:fim]) in nomes:
			return fim - inicio
	return 0


def _limpar_consulta(toks: list[Tok], com_servico: bool) -> list[Tok]:
	toks = _aparar(toks) if toks else toks
	ch = [t.chave for t in toks]
	if len(ch) > 1 and ch[0] == 'sobre':
		toks, ch = toks[1:], ch[1:]
	# "pesquisa por gatos" perde o "por"; "pesquisa por que..." é uma pergunta e fica inteira.
	if len(ch) > 1 and ch[0] == 'por' and ch[1] not in ('que', 'q'):
		toks, ch = toks[1:], ch[1:]
	if com_servico:
		for prefixo in (('um', 'video', 'de'), ('um', 'video', 'sobre'), ('videos', 'de'), ('videos', 'sobre'), ('video', 'de'), ('video', 'sobre')):
			if len(ch) > len(prefixo) and tuple(ch[: len(prefixo)]) == prefixo:
				toks = toks[len(prefixo) :]
				break
	return toks


def analisar(texto: str, nomes_com_busca: set[tuple[str, ...]] | None = None, em_dialogo: bool = False) -> Pedido:
	"""Interpreta uma frase. `nomes_com_busca` são as chaves dos serviços onde dá para pesquisar."""
	nomes = nomes_com_busca or set()
	toks = _aparar(tokens(texto))
	if not toks:
		return Pedido('vazio')
	controle = _controle(toks, em_dialogo)
	if controle:
		return controle

	while len(toks) > 1 and toks[0].chave in MODAIS:
		toks = toks[1:]
	ch = [t.chave for t in toks]

	# --- busca: "pesquisa X", "procura X no YouTube", "YouTube, procura X" ---------------------------
	pos_verbo = 0 if _e_verbo_busca(ch[0]) else None
	servico: list[Tok] = []
	if pos_verbo is None:
		for j in range(1, min(len(ch), 6)):
			if _e_verbo_busca(ch[j]):
				ini = 1 if ch[0] in EM_SERVICO else 0
				if tuple(ch[ini:j]) in nomes:
					pos_verbo, servico = j, toks[ini:j]
				break
	if pos_verbo is not None:
		resto = _aparar(toks[pos_verbo + 1 :]) if toks[pos_verbo + 1 :] else []
		rch = [t.chave for t in resto]
		if not servico and len(rch) >= 2 and rch[0] in EM_SERVICO:
			n = _maior_nome(rch, 1, nomes)
			if n:
				servico, resto = resto[1 : 1 + n], resto[1 + n :]
				rch = [t.chave for t in resto]
		# "por que o YouTube trava no Chrome": numa pergunta de porquê, o serviço citado é assunto, não destino.
		pergunta_porque = rch[:2] in (['por', 'que'], ['por', 'q']) or rch[:1] == ['porque']
		if not servico and not pergunta_porque:
			for k in range(1, len(rch) - 1):
				if rch[k] in EM_SERVICO and tuple(rch[k + 1 :]) in nomes:
					servico, resto = resto[k + 1 :], resto[:k]
					break
		consulta = _limpar_consulta(resto, bool(servico))
		return Pedido('buscar', consulta=consulta, servico=servico, verbo=True, pendurado=not consulta)

	# --- abrir: "abre o X", "vai pro X", ou só "X" ---------------------------------------------------
	verbo = ch[0] in ABRIR
	alvo = toks[1:] if verbo else toks
	site = False
	while alvo and (alvo[0].chave in CONECTORES or alvo[0].chave in SITE):
		if alvo[0].chave in SITE:
			if len(alvo) == 1:
				break
			site = True
		elif not verbo and not site and len(alvo) == 1:
			break
		alvo = alvo[1:]
	ach = [t.chave for t in alvo]
	# "abre o YouTube e pesquisa gatos"
	for k in range(1, len(ach) - 1):
		if ach[k] == 'e' and _e_verbo_busca(ach[k + 1]) and tuple(ach[:k]) in nomes:
			return Pedido('buscar', consulta=_limpar_consulta(alvo[k + 2 :], True), servico=alvo[:k], verbo=True, pendurado=not alvo[k + 2 :])
	return Pedido('abrir', alvo=alvo, verbo=verbo, site=site, pendurado=verbo and not alvo)
