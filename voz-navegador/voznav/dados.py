"""Dados locais: atalhos pessoais, serviços com busca e preferências. Tudo num JSON na pasta do usuário."""

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voznav.texto import chave_frase
from voznav.urls import validar_modelo_busca, validar_url


@dataclass
class Entrada:
	"""Um destino que pode ser aberto por nome: atalho pessoal ou serviço conhecido."""

	nome: str
	url: str
	apelidos: list[str] = field(default_factory=list)
	descricao: str = ''
	busca: str | None = None
	pessoal: bool = True

	def nomes(self) -> list[str]:
		return [self.nome, *self.apelidos]


def _s(nome: str, url: str, busca: str | None = None, *apelidos: str) -> Entrada:
	return Entrada(nome=nome, url=url, apelidos=list(apelidos), busca=busca, pessoal=False)


# Os apelidos incluem grafias que o reconhecedor costuma produzir para nomes em inglês.
SERVICOS_PADRAO: list[Entrada] = [
	_s('YouTube', 'https://www.youtube.com/', 'https://www.youtube.com/results?search_query={q}', 'you tube', 'iutube', 'iutubi'),
	_s('YouTube Music', 'https://music.youtube.com/', 'https://music.youtube.com/search?q={q}', 'youtube musica', 'youtube musico', 'you tube music', 'iutube music'),
	_s('Google', 'https://www.google.com/', 'https://www.google.com/search?q={q}', 'gugol'),
	_s('Gmail', 'https://mail.google.com/', 'https://mail.google.com/mail/u/0/#search/{q}', 'g mail', 'gemeio', 'gimeio', 'jimeio', 'jemeio', 'gmeio'),
	_s('Google Maps', 'https://www.google.com/maps', 'https://www.google.com/maps/search/{q}', 'maps', 'mapa', 'mapas'),
	_s('Google Drive', 'https://drive.google.com/', 'https://drive.google.com/drive/search?q={q}', 'drive', 'meu drive'),
	_s('Google Tradutor', 'https://translate.google.com/', 'https://translate.google.com/?sl=auto&tl=pt&text={q}', 'tradutor', 'google translate'),
	_s('GitHub', 'https://github.com/', 'https://github.com/search?q={q}', 'git hub', 'guit hub', 'guitirrabe', 'gitrab'),
	_s('WhatsApp', 'https://web.whatsapp.com/', None, 'whatsapp web', 'zap', 'zap zap', 'uatsap'),
	_s('Netflix', 'https://www.netflix.com/', 'https://www.netflix.com/search?q={q}', 'neflix', 'neflex', 'netflics', 'netiflix'),
	_s('Spotify', 'https://open.spotify.com/', 'https://open.spotify.com/search/{q}', 'spotifai', 'espotifai'),
	_s('Instagram', 'https://www.instagram.com/', None, 'insta'),
	_s('Facebook', 'https://www.facebook.com/', 'https://www.facebook.com/search/top?q={q}', 'face'),
	_s('X', 'https://x.com/', 'https://x.com/search?q={q}', 'twitter', 'tuiter'),
	_s('LinkedIn', 'https://www.linkedin.com/', 'https://www.linkedin.com/search/results/all/?keywords={q}', 'linkedin', 'linquedin'),
	_s('Amazon', 'https://www.amazon.com.br/', 'https://www.amazon.com.br/s?k={q}', 'amazon brasil'),
	_s('Mercado Livre', 'https://www.mercadolivre.com.br/', 'https://lista.mercadolivre.com.br/{q}', 'mercadolivre'),
	_s('Wikipédia', 'https://pt.wikipedia.org/', 'https://pt.wikipedia.org/w/index.php?search={q}', 'wiki'),
	_s('ChatGPT', 'https://chatgpt.com/', None, 'chat gpt', 'chat gepeto'),
	_s('Claude', 'https://claude.ai/', None, 'claude ai', 'clode'),
	_s('Twitch', 'https://www.twitch.tv/', 'https://www.twitch.tv/search?term={q}', 'tuitch'),
	_s('Reddit', 'https://www.reddit.com/', 'https://www.reddit.com/search/?q={q}', 'redit'),
	_s('Outlook', 'https://outlook.live.com/mail/', None, 'hotmail'),
	_s('G1', 'https://g1.globo.com/', 'https://g1.globo.com/busca/?q={q}', 'g um', 'ge um'),
]


@dataclass
class Config:
	modo: str = 'maos_livres'  # ou 'ptt'
	tecla: str = 'ctrl_r'
	microfone: str | None = None
	modelo: str = 'small'
	buscador: str = 'https://www.google.com/search?q={q}'
	som: bool = False
	diagnostico: bool = False
	fim_fala_ms: int = 500
	espera_extensao_ms: int = 400
	jev_ativo: bool = False
	jev_chave: str = ''
	# fala -> escrita, aplicado só ao conteúdo das buscas ("cê mais mais" -> "C++")
	pronuncias: dict[str, str] = field(default_factory=lambda: {'c mais mais': 'C++', 'ce mais mais': 'C++', 'c sharp': 'C#', 'ponto net': '.NET'})


def pasta_dados() -> Path:
	if os.environ.get('VOZNAV_DADOS'):
		return Path(os.environ['VOZNAV_DADOS'])
	if sys.platform == 'win32':
		return Path(os.environ.get('APPDATA', Path.home())) / 'VozNavegador'
	return Path.home() / '.config' / 'voznavegador'


class Dados:
	"""Carrega e grava o arquivo de dados. Gravação atômica para não corromper se o app fechar no meio."""

	def __init__(self, pasta: Path | None = None):
		self.pasta = Path(pasta) if pasta else pasta_dados()
		self.arquivo = self.pasta / 'dados.json'
		self.config = Config()
		self.atalhos: list[Entrada] = []
		self.servicos: list[Entrada] = []  # criados ou alterados pelo usuário; sobrepõem os padrão pelo nome
		self.carregar()

	def carregar(self) -> None:
		if not self.arquivo.exists():
			return
		bruto = json.loads(self.arquivo.read_text(encoding='utf-8'))
		campos = Config.__dataclass_fields__
		self.config = Config(**{k: v for k, v in bruto.get('config', {}).items() if k in campos})
		self.atalhos = [Entrada(**a) for a in bruto.get('atalhos', [])]
		self.servicos = [Entrada(**s) for s in bruto.get('servicos', [])]

	def salvar(self) -> None:
		self.pasta.mkdir(parents=True, exist_ok=True)
		conteudo = {'config': asdict(self.config), 'atalhos': [asdict(a) for a in self.atalhos], 'servicos': [asdict(s) for s in self.servicos]}
		tmp = self.arquivo.with_suffix('.tmp')
		tmp.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding='utf-8')
		os.replace(tmp, self.arquivo)

	# --- consulta -------------------------------------------------------------------------------

	def todos_servicos(self) -> list[Entrada]:
		meus = {chave_frase(s.nome) for s in self.servicos}
		return self.servicos + [s for s in SERVICOS_PADRAO if chave_frase(s.nome) not in meus]

	def catalogo(self) -> list[Entrada]:
		"""Atalhos pessoais primeiro: em empate de nome, o que o usuário cadastrou vence."""
		return self.atalhos + self.todos_servicos()

	def achar_atalho(self, nome: str) -> Entrada | None:
		alvo = chave_frase(nome)
		return next((a for a in self.atalhos if chave_frase(a.nome) == alvo), None)

	def vocabulario(self) -> list[str]:
		"""Nomes que o reconhecedor deve conhecer: atalhos do usuário e serviços."""
		return [e.nome for e in self.atalhos] + [e.nome for e in self.todos_servicos()]

	# --- alteração ------------------------------------------------------------------------------

	def gravar_atalho(self, nome: str, url: str, apelidos: list[str] | None = None, descricao: str = '') -> Entrada:
		nome = ' '.join(nome.split())
		if not nome:
			raise ValueError('O atalho precisa de um nome.')
		url = validar_url(url)
		existente = self.achar_atalho(nome)
		if existente:
			existente.nome, existente.url = nome, url
			if apelidos is not None:
				existente.apelidos = apelidos
			existente.descricao = descricao or existente.descricao
			atalho = existente
		else:
			atalho = Entrada(nome=nome, url=url, apelidos=apelidos or [], descricao=descricao)
			self.atalhos.append(atalho)
		self.salvar()
		return atalho

	def remover_atalho(self, nome: str) -> bool:
		atalho = self.achar_atalho(nome)
		if not atalho:
			return False
		self.atalhos.remove(atalho)
		self.salvar()
		return True

	def gravar_servico(self, nome: str, url: str, busca: str | None, apelidos: list[str] | None = None) -> Entrada:
		nome = ' '.join(nome.split())
		if not nome:
			raise ValueError('O serviço precisa de um nome.')
		url = validar_url(url)
		busca = validar_modelo_busca(busca) if busca else None
		self.servicos = [s for s in self.servicos if chave_frase(s.nome) != chave_frase(nome)]
		servico = Entrada(nome=nome, url=url, apelidos=apelidos or [], busca=busca, pessoal=False)
		self.servicos.append(servico)
		self.salvar()
		return servico

	def remover_servico(self, nome: str) -> bool:
		antes = len(self.servicos)
		self.servicos = [s for s in self.servicos if chave_frase(s.nome) != chave_frase(nome)]
		self.salvar()
		return len(self.servicos) != antes

	def acrescentar_apelido(self, entrada: Entrada, apelido: str) -> None:
		"""Guarda uma pronúncia aceita pelo usuário. Serviço padrão vira uma cópia editável."""
		if entrada not in self.atalhos and entrada not in self.servicos:
			entrada = Entrada(**asdict(entrada))
			self.servicos.append(entrada)
		if chave_frase(apelido) not in {chave_frase(n) for n in entrada.nomes()}:
			entrada.apelidos.append(apelido)
		self.salvar()

	def definir_buscador(self, modelo: str) -> None:
		self.config.buscador = validar_modelo_busca(modelo)
		self.salvar()
