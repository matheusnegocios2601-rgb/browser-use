"""Jev: testado contra um servidor HTTP local que imita o formato documentado da API da TypeSafe.

NÃO foi verificado contra o serviço real (acesso por lista de espera, sem chave disponível neste ambiente).
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from voznav.dados import Config
from voznav.jev import Jev, criar_desempate
from voznav.sessao import Sessao


@pytest.fixture
def servidor():
	estado = {'resposta': {}, 'pedidos': [], 'atraso': 0.0}

	class Manipulador(BaseHTTPRequestHandler):
		def do_POST(self):
			import time

			corpo = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
			estado['pedidos'].append((self.headers['Authorization'], corpo))
			time.sleep(estado['atraso'])
			dados = json.dumps(estado['resposta']).encode()
			self.send_response(200)
			self.send_header('Content-Type', 'application/json')
			self.end_headers()
			self.wfile.write(dados)

		def log_message(self, *a):
			pass

	srv = HTTPServer(('127.0.0.1', 0), Manipulador)
	threading.Thread(target=srv.serve_forever, daemon=True).start()
	estado['url'] = f'http://127.0.0.1:{srv.server_port}/v1/systemone'
	yield estado
	srv.shutdown()


def _resposta(escolha, confianca, probs):
	return {'answers': {'destino': {'choice': escolha, 'confidence': confianca, 'probabilities': probs}}, 'usage': {'input_tokens': 90, 'output_tokens': 4}}


def test_formato_do_pedido_e_escolha_folgada(servidor, dados):
	servidor['resposta'] = _resposta('op2', 0.93, {'op1': 0.05, 'op2': 0.9, 'nenhum': 0.05})
	jev = Jev('chave-de-teste', url=servidor['url'])
	bancos = [a for a in dados.atalhos if 'Banco' in a.nome]
	assert jev.escolher('aquele banco laranja', bancos).nome == 'Banco Inter'
	autorizacao, corpo = servidor['pedidos'][0]
	assert autorizacao == 'Bearer chave-de-teste' and corpo['model'] == 'jev-latest'
	pergunta = corpo['questions']['destino']
	assert pergunta['type'] == 'choice' and set(pergunta['criteria']) == {'op1', 'op2', 'nenhum'}
	assert 'aquele banco laranja' in corpo['state']
	assert 'pagina-inicial' not in json.dumps(corpo)  # só o domínio vai, não a URL completa


@pytest.mark.parametrize(
	'resposta',
	[
		_resposta('nenhum', 0.9, {'op1': 0.1, 'op2': 0.1, 'nenhum': 0.8}),
		_resposta('op1', 0.4, {'op1': 0.9, 'op2': 0.05, 'nenhum': 0.05}),  # confiança baixa
		_resposta('op1', 0.9, {'op1': 0.52, 'op2': 0.45, 'nenhum': 0.03}),  # sem folga
		_resposta('op9', 0.9, {'op9': 0.99}),  # opção inexistente
		{'erro': 'formato inesperado'},
	],
)
def test_qualquer_duvida_volta_para_o_fluxo_local(servidor, dados, resposta):
	servidor['resposta'] = resposta
	assert Jev('k', url=servidor['url']).escolher('meu banco', dados.atalhos[1:]) is None


def test_demora_ou_rede_fora_nao_trava(servidor, dados):
	servidor['atraso'] = 0.5
	servidor['resposta'] = _resposta('op1', 0.99, {'op1': 0.99})
	assert Jev('k', url=servidor['url'], limite_s=0.1).escolher('meu banco', dados.atalhos) is None
	assert Jev('k', url='http://127.0.0.1:9/x', limite_s=0.2).escolher('meu banco', dados.atalhos) is None


def test_desligado_por_padrao_e_sessao_usa_so_quando_ha_empate(servidor, dados, monkeypatch):
	monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
	assert criar_desempate(Config()) is None
	assert criar_desempate(Config(jev_ativo=True)) is None  # sem chave
	servidor['resposta'] = _resposta('op2', 0.95, {'op1': 0.03, 'op2': 0.95, 'nenhum': 0.02})
	s = Sessao(dados, desempate=Jev('k', url=servidor['url']).escolher)
	assert s.processar('abre o YouTube').via == 'nome' and servidor['pedidos'] == []  # caminho comum: sem rede
	assert s.processar('pesquisa gatos').via == 'busca' and servidor['pedidos'] == []
	d = s.processar('abre meu banco')
	assert (d.tipo, d.via, d.rotulo) == ('abrir', 'jev', 'Banco Inter') and len(servidor['pedidos']) == 1
	servidor['resposta'] = _resposta('nenhum', 0.9, {'nenhum': 0.9, 'op1': 0.05, 'op2': 0.05})
	assert s.processar('abre meu banco').tipo == 'escolher'  # Jev em dúvida: pergunta como sempre
