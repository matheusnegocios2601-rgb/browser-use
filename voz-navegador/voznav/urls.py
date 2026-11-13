"""Endereços: validação, endereço ditado e montagem de buscas. Só HTTP e HTTPS saem daqui."""

import ipaddress
import re
from urllib.parse import quote, quote_plus, urlsplit

from voznav.texto import Tok, dobrar

TLDS = frozenset(
	'com net org br io dev app gov edu tv me co ai info biz blog shop store online site tech xyz '
	'pt us uk es fr de it ar mx cl uy py pe ca jp cn eu gg ly fm to cc so sh art page cloud live news'.split()
)

_SIMBOLOS = {
	'ponto': '.', 'pontos': '.', 'dot': '.', 'barra': '/', 'traco': '-', 'hifen': '-', 'tracinho': '-',
	'underline': '_', 'underscore': '_', 'sublinhado': '_', 'arroba': '@', 'interrogacao': '?', 'igual': '=',
	'cerquilha': '#', 'hashtag': '#',
}
_W = {'dabliu', 'dablio', 'dabliou', 'w'}
_HOST = re.compile(r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,23}$')
_CAMINHO_OK = re.compile(r'^[^\s<>"{}|\\^`\x00-\x1f\x7f]*$')


def validar_url(url: str) -> str:
	"""Devolve a URL intacta se for HTTP(S) bem formada; ValueError com mensagem em português caso contrário."""
	url = url.strip()
	if not url or not _CAMINHO_OK.match(url):
		raise ValueError('O endereço tem espaços ou caracteres inválidos.')
	p = urlsplit(url)
	if p.scheme.lower() not in ('http', 'https'):
		raise ValueError('Só abro endereços http:// ou https://.')
	host = (p.hostname or '').lower()
	if not host:
		raise ValueError('O endereço não tem um domínio.')
	try:
		_ = p.port
	except ValueError:
		raise ValueError('A porta do endereço é inválida.') from None
	if host != 'localhost' and not _HOST.match(host):
		try:
			ipaddress.ip_address(host)
		except ValueError:
			raise ValueError(f'"{host}" não parece um domínio válido.') from None
	return url


def completar_url(texto: str) -> str:
	"""Para endereço digitado ou colado: acrescenta https:// se faltar e valida."""
	texto = texto.strip()
	if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', texto):
		texto = 'https://' + texto
	return validar_url(texto)


def endereco_falado(toks: list[Tok]) -> str | None:
	"""Converte "github ponto com barra settings" em URL, ou None se não houver evidência de endereço.

	Evidência = depois de trocar as palavras-símbolo, sobra um domínio com TLD conhecido. É isso que impede
	"ponto de equilíbrio" de virar endereço: "de" não é TLD e a frase não forma um domínio.
	"""
	partes: list[str] = []
	i = 0
	while i < len(toks):
		c = toks[i].chave
		prox = toks[i + 1].chave if i + 1 < len(toks) else ''
		if c == 'dois' and prox in ('pontos', 'ponto'):
			partes.append(':')
			i += 2
		elif c == 'jogo' and prox == 'da' and i + 2 < len(toks) and toks[i + 2].chave == 'velha':
			partes.append('#')
			i += 3
		elif c in _W and prox in _W and i + 2 < len(toks) and toks[i + 2].chave in _W:
			partes.append('www')
			i += 3
		elif c in _SIMBOLOS:
			partes.append(_SIMBOLOS[c])
			i += 1
		else:
			partes.append(toks[i].orig)
			i += 1
	junto = ''.join(partes)
	esquema = 'https://'
	m = re.match(r'^(https?):/{0,2}', junto, re.I)
	if m:
		esquema = m.group(1).lower() + '://'
		junto = junto[m.end():]
	corte = re.search(r'[/?#]', junto)
	host, resto = (junto[: corte.start()], junto[corte.start():]) if corte else (junto, '')
	host = dobrar(host).strip('.')
	if not _HOST.match(host) or host.rsplit('.', 1)[-1] not in TLDS:
		return None
	try:
		return validar_url(esquema + host + resto.rstrip('.,!?;'))
	except ValueError:
		return None


def validar_modelo_busca(modelo: str) -> str:
	"""Um modelo de busca é uma URL http(s) com exatamente um {q}."""
	modelo = modelo.strip()
	if modelo.count('{q}') != 1:
		raise ValueError('O modelo precisa conter {q} exatamente uma vez, onde entra o texto buscado.')
	validar_url(modelo.replace('{q}', 'x'))
	if '{q}' in urlsplit(modelo).netloc:
		raise ValueError('O {q} não pode ficar no domínio.')
	return modelo


def montar_busca(modelo: str, consulta: str) -> str:
	"""Substitui {q} com a codificação certa para o lugar onde ele está (caminho/fragmento ou parâmetros)."""
	antes, _, _ = modelo.partition('{q}')
	em_parametros = '?' in antes and '#' not in antes
	codificado = quote_plus(consulta, safe='') if em_parametros else quote(consulta, safe='')
	return validar_url(modelo.replace('{q}', codificado))
