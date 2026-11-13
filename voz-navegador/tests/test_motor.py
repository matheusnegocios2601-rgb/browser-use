"""Testes do motor com áudio SINTÉTICO (rajadas de ruído no lugar da voz) e um reconhecedor roteirizado.

Verificam o que independe do reconhecimento: uma abertura por fala, descarte de resultados atrasados,
tolerância a pausa curta, pressionar-para-falar e falha de microfone. As aberturas são interceptadas.
"""

import time

import numpy as np
import pytest

from voznav.captura import Captura, ErroMicrofone
from voznav.dados import Dados
from voznav.fala import Resultado
from voznav.motor import Motor
from voznav.sessao import Sessao

YT, YTM = 'https://www.youtube.com/', 'https://music.youtube.com/'


class Roteiro:
	"""Reconhecedor de mentira: devolve as frases do roteiro; parciais devolvem o começo da frase."""

	def __init__(self, *frases, atraso=0.0):
		self.frases, self.atraso, self.chamadas, self.precisas = list(frases), atraso, 0, 0

	def transcrever(self, audio, preciso=False):
		self.chamadas += 1
		self.precisas += preciso
		time.sleep(self.atraso)
		voz = float(np.mean(np.abs(audio) > 0.05))
		if not self.frases or voz < 0.02:
			return Resultado('', False, 0.0)
		frase = self.frases[0]
		# a mesma fala pode ser transcrita várias vezes (parcial, especulativa, final): o texto depende só do áudio
		if isinstance(frase, dict):
			frase = frase['longa'] if len(audio) > frase['corte'] else frase['curta']
		return Resultado(frase, frase != '<ruido>', 0.0)


class Bancada:
	def __init__(self, tmp_path, rec, modo='maos_livres'):
		self.t = 100.0
		self.abertas: list[str] = []
		self.eventos: list[tuple] = []
		dados = Dados(tmp_path)
		dados.config.modo = modo
		dados.gravar_atalho('Banco do Brasil', 'https://www.bb.com.br/')
		dados.gravar_atalho('Banco Inter', 'https://bancointer.com.br/')
		self.rec = rec
		self.motor = Motor(Sessao(dados), rec, self.abertas.append, lambda tipo, **k: self.eventos.append((tipo, k)), relogio=lambda: self.t)
		self.motor.ouvir()

	def _tocar(self, ms, amplitude):
		rng = np.random.default_rng(1)
		for _ in range(ms // 20):
			self.t += 0.02
			self.motor.alimentar((rng.standard_normal(320) * amplitude).astype(np.float32))
			self.assentar()

	def falar(self, ms=600):
		self._tocar(ms, 0.2)

	def silencio(self, ms=1000):
		self._tocar(ms, 0.0005)

	def assentar(self):
		limite = time.time() + 3
		while not self.motor.ocioso() and time.time() < limite:
			time.sleep(0.0005)
		time.sleep(0.0005)

	def proxima(self, frase):
		self.rec.frases = [frase]

	def decisoes(self):
		return [k['decisao'].tipo for tipo, k in self.eventos if tipo == 'decisao']


def test_uma_fala_abre_uma_vez_mesmo_com_parciais_e_finais_repetidos(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix'))
	b.falar(2400)
	b.silencio()
	assert b.abertas == ['https://www.netflix.com/']
	assert b.rec.chamadas >= 3  # houve parciais + final para a mesma fala
	assert any(tipo == 'parcial' for tipo, _ in b.eventos)
	# um segundo evento "final" da mesma fala (reentrega) não abre de novo
	fala_uid = max(b.motor._despachadas)
	from voznav.motor import _Fala

	b.motor._concluir(_Fala(uid=fala_uid, epoca=b.motor._epoca, modo='maos_livres'), Resultado('abre a Netflix', True, 0))
	assert b.abertas == ['https://www.netflix.com/'] and b.motor.metricas.duplicatas_bloqueadas == 1


def test_duas_falas_iguais_sao_dois_pedidos(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix'))
	for _ in range(2):
		b.falar()
		b.silencio()
	assert b.abertas == ['https://www.netflix.com/'] * 2
	assert b.motor.metricas.duplicatas_bloqueadas == 0


def test_dois_comandos_em_sequencia(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix'))
	b.falar()
	b.silencio()
	b.proxima('pesquisa clima amanhã')
	b.falar()
	b.silencio()
	assert b.abertas == ['https://www.netflix.com/', 'https://www.google.com/search?q=clima+amanh%C3%A3']
	assert b.motor.estado == 'ouvindo'  # voltou a ouvir sozinho


def test_pausar_descarta_resultado_atrasado(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix', atraso=0.15))
	rng = np.random.default_rng(1)
	for amplitude, n in ((0.2, 30), (0.0005, 30)):  # fala e silêncio, sem esperar o reconhecedor lento
		for _ in range(n):
			b.t += 0.02
			b.motor.alimentar((rng.standard_normal(320) * amplitude).astype(np.float32))
	assert b.motor.estado == 'interpretando'
	b.motor.pausar()
	b.assentar()
	time.sleep(0.3)
	assert b.abertas == [] and b.motor.estado == 'pausado'
	b.motor.ouvir()  # e retoma normalmente
	b.rec.atraso = 0
	b.falar()
	b.silencio()
	assert b.abertas == ['https://www.netflix.com/']


def test_pausar_escuta_por_voz_para_de_processar_audio(tmp_path):
	b = Bancada(tmp_path, Roteiro('pausar escuta'))
	b.falar()
	b.silencio()
	assert b.motor.estado == 'pausado'
	b.proxima('abre a Netflix')
	b.falar()
	b.silencio()
	assert b.abertas == []


def test_escolha_segundo_e_cancelar(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre meu banco'))
	b.falar()
	b.silencio()
	assert b.motor.estado == 'escolha' and b.abertas == []
	b.proxima('o segundo')
	b.falar(400)
	b.silencio()
	assert b.abertas == ['https://bancointer.com.br/'] and b.motor.estado == 'ouvindo'
	b.proxima('abre meu banco')
	b.falar()
	b.silencio()
	b.proxima('cancelar')
	b.falar(400)
	b.silencio()
	assert b.motor.estado == 'ouvindo' and len(b.abertas) == 1
	b.proxima('o segundo')
	b.falar(400)
	b.silencio()
	assert len(b.abertas) == 1  # a ação pendente foi descartada de verdade


def test_pausa_curta_no_meio_do_nome_abre_so_youtube_music(tmp_path):
	b = Bancada(tmp_path, Roteiro({'curta': 'Abre o YouTube', 'longa': 'Abre o YouTube Music', 'corte': 16000 * 1.9}))
	b.falar(800)
	b.silencio(800)  # pausa maior que o fim de fala (500 ms), menor que a tolerância total (900 ms)
	assert b.abertas == []  # segurou: "YouTube" pode continuar
	b.falar(500)
	b.silencio(1500)
	assert b.abertas == [YTM]


def test_pausa_curta_com_reconhecedor_lento_ainda_junta_as_duas_partes(tmp_path):
	"""A segunda parte começa antes de a transcrição da primeira chegar: o motor junta quando ela chega."""
	b = Bancada(tmp_path, Roteiro({'curta': 'Abre o YouTube', 'longa': 'Abre o YouTube Music', 'corte': 16000 * 1.9}, atraso=0.1))
	rng = np.random.default_rng(1)
	for amplitude, ms in ((0.2, 800), (0.0005, 650), (0.2, 500), (0.0005, 1500)):
		for _ in range(ms // 20):
			b.t += 0.02
			b.motor.alimentar((rng.standard_normal(320) * amplitude).astype(np.float32))
	time.sleep(0.6)
	b.assentar()
	b.silencio(600)
	assert b.abertas == [YTM]


def test_frases_seguidas_sem_relacao_nao_sao_juntadas(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix'))
	b.falar(800)
	b.silencio(700)
	assert b.abertas == ['https://www.netflix.com/']  # não segura: "Netflix" não é começo de outro nome
	b.proxima('pesquisa gatos')
	b.falar(600)
	b.silencio()
	assert len(b.abertas) == 2


def test_youtube_sozinho_abre_depois_da_tolerancia(tmp_path):
	b = Bancada(tmp_path, Roteiro('Abre o YouTube'))
	b.falar(800)
	b.silencio(800)
	assert b.abertas == []
	b.silencio(400)
	assert b.abertas == [YT]
	m = b.motor.metricas.medidas[-1]
	assert 0.3 < m.espera_extensao < 0.5  # a espera proposital aparece na medição, não fica escondida


def test_ruido_e_silencio_nao_abrem_nada(tmp_path):
	b = Bancada(tmp_path, Roteiro('<ruido>'))
	b.silencio(2000)
	assert b.rec.chamadas == 0  # silêncio nem chega ao reconhecedor
	b.falar(60)  # estalo curto
	b.silencio()
	assert b.decisoes() == []
	b.falar(700)  # ruído longo: o reconhecedor diz que não é confiável
	b.silencio()
	assert b.decisoes() == ['repetir'] and b.abertas == []
	assert b.motor.metricas.resumo()['pedidos_de_repeticao'] == 1


def test_segunda_passada_so_quando_a_primeira_nao_leva_a_destino(tmp_path):
	class DuasPassadas(Roteiro):
		def transcrever(self, audio, preciso=False):
			r = super().transcrever(audio, preciso)
			return Resultado('Abre a Netflix' if preciso else 'Abençoa-te', True, 0.0) if r.texto else r

	b = Bancada(tmp_path, DuasPassadas('x'))
	b.falar()
	b.silencio()
	assert b.abertas == ['https://www.netflix.com/'] and b.rec.precisas == 1 and b.decisoes() == ['abrir']
	b2 = Bancada(tmp_path / 'b2', Roteiro('abre a Netflix'))
	b2.falar()
	b2.silencio()
	assert b2.rec.precisas == 0  # caminho comum: uma passada só


def test_pressionar_para_falar_conclui_ao_soltar(tmp_path):
	b = Bancada(tmp_path, Roteiro('abre a Netflix'), modo='ptt')
	assert b.motor.estado == 'pronto'
	b.falar()  # sem a tecla: ignorado
	b.silencio()
	assert b.abertas == []
	b.motor.pressionar()
	assert b.motor.estado == 'ouvindo'
	b.falar()
	b.motor.soltar()  # sem esperar silêncio
	b.assentar()
	assert b.abertas == ['https://www.netflix.com/'] and b.motor.estado == 'pronto'
	b.motor.pressionar()
	b.silencio(300)
	b.motor.soltar()
	b.assentar()
	assert len(b.abertas) == 1 and b.decisoes()[-1] == 'repetir'


def test_texto_digitado_segue_as_mesmas_regras(tmp_path):
	b = Bancada(tmp_path, Roteiro())
	assert b.motor.texto_digitado('abre github ponto com barra settings').url == 'https://github.com/settings'
	assert b.abertas == ['https://github.com/settings']


def test_destino_que_nao_e_http_nunca_chega_ao_sistema(tmp_path):
	from voznav.abrir import abrir_no_navegador

	for ruim in ['file:///C:/Windows/System32/calc.exe', 'calc.exe', 'javascript:alert(1)', 'https://x.com/ & calc']:
		with pytest.raises(ValueError):
			abrir_no_navegador(ruim)


def test_microfone_ausente_da_causa_e_acao_e_permite_tentar_de_novo():
	"""Hardware real ausente: este ambiente de teste não tem microfone, então a falha é verdadeira."""
	erros = []
	captura = Captura(lambda bloco: None, erros.append)
	for _ in range(2):  # tentar de novo não trava nem exige reiniciar
		with pytest.raises(ErroMicrofone) as info:
			captura.iniciar()
		assert info.value.causa and 'Tentar de novo' in info.value.acao
		assert not captura.ativo
	with pytest.raises(ErroMicrofone) as info:
		captura.iniciar('Microfone que não existe')
	assert 'não foi encontrado' in info.value.causa
