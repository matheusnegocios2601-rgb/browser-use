"""Testes de TEXTO: regras de interpretação, sem áudio. Cada frase é o que o reconhecedor entregaria."""

from urllib.parse import parse_qs, urlsplit

import pytest

from voznav.dados import Dados
from voznav.sessao import Sessao
from voznav.texto import tokens
from voznav.urls import endereco_falado, montar_busca, validar_modelo_busca, validar_url

YT = 'https://www.youtube.com/'
YTM = 'https://music.youtube.com/'


def q(url: str, chave: str = 'q') -> str:
	return parse_qs(urlsplit(url).query)[chave][0]


# --- contrato de comportamento (tabela do pedido) --------------------------------------------------


@pytest.mark.parametrize('frase', ['YouTube', 'YouTube.', 'vai pro YouTube aí', 'Abre o YouTube, por favor.', 'quero abrir o youtube', 'entra no YouTube'])
def test_abre_youtube(sessao, frase):
	d = sessao.processar(frase)
	assert (d.tipo, d.url) == ('abrir', YT)


@pytest.mark.parametrize('frase', ['YouTube Music', 'Abre o YouTube... Music', 'Abre o YouTube… Music.', 'abre o youtube music aí'])
def test_youtube_music_e_pausa_curta(sessao, frase):
	d = sessao.processar(frase)
	assert (d.tipo, d.url) == ('abrir', YTM)


def test_youtube_sozinho_avisa_que_a_frase_pode_continuar(sessao):
	assert sessao.processar('Abre o YouTube').extensivel is True
	assert sessao.processar('Abre o YouTube Music').extensivel is False
	assert sessao.processar('abre a Netflix').extensivel is False


@pytest.mark.parametrize(
	'frase',
	['Procura análise do Galaxy S no YouTube', 'YouTube, procura análise do Galaxy S', 'no YouTube pesquisa análise do Galaxy S', 'pesquisa no YouTube análise do Galaxy S', 'abre o YouTube e procura análise do Galaxy S'],
)
def test_busca_dentro_do_youtube(sessao, frase):
	d = sessao.processar(frase)
	assert d.tipo == 'abrir' and d.url.startswith('https://www.youtube.com/results?')
	assert q(d.url, 'search_query') == 'análise do Galaxy S'


def test_pergunta_com_nome_de_servico_vai_ao_buscador_geral(sessao):
	d = sessao.processar('Pesquisa por que o YouTube trava no Chrome')
	assert d.url.startswith('https://www.google.com/search?') and q(d.url) == 'por que o YouTube trava no Chrome'
	d = sessao.processar('pesquisa por que o Chrome trava no YouTube')
	assert d.url.startswith('https://www.google.com/search?') and q(d.url) == 'por que o Chrome trava no YouTube'


def test_verbo_abrir_dentro_da_consulta(sessao):
	d = sessao.processar('Pesquisa como abrir o Gmail')
	assert d.url.startswith('https://www.google.com/search?') and q(d.url) == 'como abrir o Gmail'


@pytest.mark.parametrize(
	('frase', 'url'),
	[
		('Abre github ponto com barra settings', 'https://github.com/settings'),
		('abre GitHub.com barra settings', 'https://github.com/settings'),
		('vai para exemplo ponto com ponto br', 'https://exemplo.com.br'),
		('abre dábliu dábliu dábliu ponto uol ponto com ponto br barra esporte', 'https://www.uol.com.br/esporte'),
		('minha loja ponto com', 'https://minhaloja.com'),
	],
)
def test_endereco_ditado(sessao, frase, url):
	d = sessao.processar(frase)
	assert (d.tipo, d.url, d.via) == ('abrir', url, 'endereco')


def test_ponto_de_equilibrio_continua_sendo_pesquisa(sessao):
	d = sessao.processar('Pesquisa o que é ponto de equilíbrio')
	assert d.via == 'busca' and q(d.url) == 'o que é ponto de equilíbrio'
	assert endereco_falado(tokens('ponto de equilíbrio')) is None
	assert endereco_falado(tokens('barra de ferramentas')) is None


@pytest.mark.parametrize('frase', ['Meu painel', 'meu painel.', 'abre meu painel', 'painel', 'abre o painel aí'])
def test_atalho_preserva_caminho_parametros_e_fragmento(sessao, frase):
	d = sessao.processar(frase)
	assert (d.tipo, d.url) == ('abrir', 'https://app.exemplo.com/vendas/painel?periodo=30d&aba=2#resumo')


def test_atalho_por_descricao(sessao):
	d = sessao.processar('Aquela página que eu salvei pra acompanhar vendas')
	assert (d.tipo, d.via) == ('abrir', 'descricao') and d.url.startswith('https://app.exemplo.com/vendas/painel')


def test_dois_atalhos_plausiveis_pergunta_e_aceita_ordinal(sessao):
	d = sessao.processar('Abre meu banco')
	assert d.tipo == 'escolher' and [r for r, _ in d.opcoes] == ['Banco do Brasil', 'Banco Inter']
	assert 'Banco do Brasil' in d.mensagem and 'Banco Inter' in d.mensagem
	d = sessao.processar('o segundo')
	assert (d.tipo, d.url) == ('abrir', 'https://internetbanking.bancointer.com.br/')
	assert not sessao.aguardando


def test_escolha_aceita_primeiro_nome_e_cancelar(sessao):
	sessao.processar('abre meu banco')
	assert sessao.processar('o primeiro.').url == 'https://www.bb.com.br/pbb/pagina-inicial'
	sessao.processar('abre meu banco')
	assert sessao.processar('o Inter').url == 'https://internetbanking.bancointer.com.br/'
	sessao.processar('abre meu banco')
	d = sessao.processar('Cancelar.')
	assert d.tipo == 'cancelado' and not sessao.aguardando
	assert sessao.processar('o segundo').tipo == 'repetir'  # a ação pendente foi descartada


def test_escolha_resposta_estranha_repete_a_pergunta_e_comando_novo_substitui(sessao):
	sessao.processar('abre meu banco')
	assert sessao.processar('o terceiro').tipo == 'escolher'
	assert sessao.processar('hum talvez').tipo == 'escolher'
	assert sessao.processar('abre o YouTube').url == YT
	assert not sessao.aguardando


def test_site_desconhecido_pesquisa_o_nome_sem_adivinhar_dominio(sessao):
	d = sessao.processar('Abre o site da Loja Exemplo')
	assert d.via == 'busca_site' and d.url.startswith('https://www.google.com/search?') and q(d.url) == 'Loja Exemplo'
	assert sessao.processar('abre a Lojinha Exemplo').via == 'busca_nome'


def test_pausar_escuta(sessao):
	for frase in ['Pausar escuta', 'pausa a escuta por favor', 'para de ouvir']:
		assert sessao.processar(frase).tipo == 'pausar'


# --- separação comando x conteúdo --------------------------------------------------------------------


def test_consulta_preserva_acentos_ingles_numeros_e_simbolos(sessao):
	assert q(sessao.processar('Procura C++ no YouTube').url, 'search_query') == 'C++'
	assert q(sessao.processar('procura cê mais mais no YouTube').url, 'search_query') == 'C++'
	assert q(sessao.processar('Pesquisa preço do iPhone 15 Pro Max 256GB').url) == 'preço do iPhone 15 Pro Max 256GB'
	assert q(sessao.processar('pesquisa, por favor, AT&T 50% off').url) == 'AT&T 50% off'
	d = sessao.processar('procura São João del-Rei no Maps')
	assert d.url == 'https://www.google.com/maps/search/S%C3%A3o%20Jo%C3%A3o%20del-Rei'


def test_muleta_so_sai_das_bordas(sessao):
	assert q(sessao.processar('pesquisa aí como fazer pão por favor').url) == 'como fazer pão'
	assert q(sessao.processar('pesquisa open AI').url) == 'open AI'


def test_verbo_com_erro_de_reconhecimento(sessao):
	assert q(sessao.processar('Esquisa como abrir o Gmail.').url) == 'como abrir o Gmail'
	assert q(sessao.processar('Desquisa por que o YouTube trava no Chrome.').url) == 'por que o YouTube trava no Chrome'


def test_frases_como_o_reconhecedor_realmente_entregou_na_bancada(sessao):
	"""Transcrições reais (com erros) observadas na bancada de áudio."""
	assert sessao.processar('Abia Netflix.').url == 'https://www.netflix.com/'
	assert sessao.processar('Abreu YouTube.').url == YT and sessao.processar('Abreu YouTube.').extensivel
	assert sessao.processar('Apre meu painel.').url.startswith('https://app.exemplo.com/vendas/painel')
	assert sessao.processar('Noupainel.').url.startswith('https://app.exemplo.com/vendas/painel')
	assert sessao.processar('Aquela página que eu só veio para acompanhar vendas.').via == 'descricao'
	assert q(sessao.processar('Desquiso o que é ponto de equilíbrio.').url) == 'o que é ponto de equilíbrio'
	assert q(sessao.processar('Procur análise do Galaxy S no YouTube.').url, 'search_query') == 'análise do Galaxy S'
	assert sessao.processar('procuro emprego').tipo == 'abrir'  # busca: não confunde com atalho
	sessao.processar('Apremeu o Banco.')
	assert sessao.processar('Cancellar.').tipo == 'cancelado'
	assert sessao.processar('Posar escuta.').tipo == 'pausar'


def test_nome_de_servico_com_erro_de_reconhecimento(sessao):
	assert sessao.processar('abre a neflex').url == 'https://www.netflix.com/'
	assert sessao.processar('abre o Netiflix').url == 'https://www.netflix.com/'
	assert sessao.processar('abre o guit hub').url == 'https://github.com/'


# --- ruído e frases incompletas ------------------------------------------------------------------------


@pytest.mark.parametrize('frase', ['', '...', 'hum', 'tá bom então', 'que horas são'])
def test_ruido_pede_para_repetir_e_nao_abre_nada(sessao, frase):
	assert sessao.processar(frase).tipo == 'repetir'


@pytest.mark.parametrize('frase', ['abre o', 'procura', 'pesquisa no YouTube', 'abre'])
def test_frase_pendurada_nao_dispara_busca(sessao, frase):
	d = sessao.processar(frase)
	assert d.tipo == 'repetir' and d.extensivel


def test_repeticao_intencional_gera_duas_decisoes_iguais(sessao):
	assert sessao.processar('YouTube').url == sessao.processar('YouTube').url == YT


# --- personalização ------------------------------------------------------------------------------------


def test_fluxo_criar_atalho_por_voz_e_persistencia(tmp_path):
	dados = Dados(tmp_path)
	s = Sessao(dados)
	assert 'endereço' in s.processar('criar atalho painel de vendas').mensagem
	d = s.processar('app ponto minhaempresa ponto com ponto br barra vendas barra painel')
	assert d.via == 'confirmar_atalho' and d.rotulo == 'painel de vendas' and d.url == 'https://app.minhaempresa.com.br/vendas/painel'
	assert s.processar('salvar').via == 'atalho_salvo'
	assert s.processar('abre meu painel de vendas').url == 'https://app.minhaempresa.com.br/vendas/painel'  # mesma sessão
	reaberto = Sessao(Dados(tmp_path))  # fechou e abriu o app
	assert reaberto.processar('abre meu painel de vendas').url == 'https://app.minhaempresa.com.br/vendas/painel'


def test_criar_atalho_colando_endereco_e_corrigindo_antes_de_salvar(tmp_path):
	s = Sessao(Dados(tmp_path))
	s.processar('cria um atalho relatório')
	d = s.informar_endereco('app.exemplo.com/r?id=7&x=a%20b#topo')
	assert d.url == 'https://app.exemplo.com/r?id=7&x=a%20b#topo'
	assert s.processar('corrigir nome relatório mensal').rotulo == 'relatório mensal'
	assert 'endereço' in s.processar('endereço errado').mensagem
	assert s.processar('exemplo ponto com barra novo').url == 'https://exemplo.com/novo'
	s.confirmar_atalho('Relatório Mensal', 'https://exemplo.com/novo?ok=1')  # correção manual na tela
	assert s.processar('relatório mensal').url == 'https://exemplo.com/novo?ok=1'


def test_criar_atalho_cancelar_nao_salva_e_endereco_invalido_nao_avanca(tmp_path):
	dados = Dados(tmp_path)
	s = Sessao(dados)
	s.processar('criar atalho teste')
	assert s.processar('isso não é endereço').via == ''
	assert s.informar_endereco('javascript:alert(1)').via == ''
	assert s.informar_endereco('file:///C:/Windows/system32/calc.exe').via == ''
	s.processar('exemplo ponto com')
	assert s.processar('cancelar').tipo == 'cancelado'
	assert dados.atalhos == [] and not s.aguardando


def test_nome_existente_mostra_destino_que_sera_substituido(sessao):
	sessao.processar('criar atalho painel')
	d = sessao.processar('novo ponto exemplo ponto com')
	assert 'substitui' in d.mensagem and 'https://app.exemplo.com/vendas/painel' in d.mensagem
	sessao.processar('salvar')
	assert sessao.processar('meu painel').url == 'https://novo.exemplo.com'
	assert len([a for a in sessao.dados.atalhos if a.nome == 'painel']) == 1


def test_correcao_repetida_oferece_apelido_e_so_memoriza_se_aceitar(dados):
	relogio = [0.0]
	s = Sessao(dados, agora=lambda: relogio[0])
	for _ in range(2):
		assert s.processar('peinel').tipo == 'repetir'
		relogio[0] += 5
		d = s.processar('meu painel')
	assert 'apelido' in d.oferta and d.tipo == 'abrir'
	assert s.processar('não').tipo == 'dialogo'
	assert s.processar('peinel').tipo == 'repetir'  # recusou: nada foi memorizado
	s.processar('meu painel')
	assert not s.aguardando  # e não insiste

	s2 = Sessao(dados, agora=lambda: relogio[0])
	for _ in range(2):
		s2.processar('abre o peinel')
		d = s2.processar('abre o painel')
	assert d.oferta and s2.processar('sim').via == 'apelido_salvo'
	assert Sessao(Dados(dados.pasta)).processar('peinel').url.startswith('https://app.exemplo.com/vendas/painel')


def test_buscador_geral_configuravel_e_servico_de_busca_cadastrado(dados):
	dados.definir_buscador('https://duckduckgo.com/?q={q}')
	dados.gravar_servico('Estante', 'https://www.estantevirtual.com.br/', 'https://www.estantevirtual.com.br/busca?q={q}', ['estante virtual'])
	s = Sessao(dados)
	assert s.processar('pesquisa clima amanhã').url == 'https://duckduckgo.com/?q=clima+amanh%C3%A3'
	assert s.processar('procura Dom Casmurro na estante virtual').url == 'https://www.estantevirtual.com.br/busca?q=Dom+Casmurro'
	assert Sessao(Dados(dados.pasta)).processar('abre a estante').url == 'https://www.estantevirtual.com.br/'


@pytest.mark.parametrize('modelo', ['https://x.com/busca', 'ftp://x.com/?q={q}', 'https://x.com/?a={q}&b={q}', 'https://{q}.com/', 'javascript:{q}', 'x.com/?q={q}'])
def test_modelo_de_busca_invalido_e_recusado(modelo):
	with pytest.raises(ValueError):
		validar_modelo_busca(modelo)


@pytest.mark.parametrize('url', ['file:///c:/x.exe', 'javascript:alert(1)', 'cmd.exe /c calc', 'https://', 'http://exa mple.com', 'https://exemplo.com/a b', 'ms-settings:privacy', '\\\\servidor\\x', 'https://x.com/"&calc'])
def test_so_http_e_https_bem_formados(url):
	with pytest.raises(ValueError):
		validar_url(url)


def test_codificacao_de_parametros():
	assert montar_busca('https://s.com/?q={q}&x=1', 'a&b=c #d') == 'https://s.com/?q=a%26b%3Dc+%23d&x=1'
	assert montar_busca('https://s.com/b/{q}', 'a/b c?') == 'https://s.com/b/a%2Fb%20c%3F'
