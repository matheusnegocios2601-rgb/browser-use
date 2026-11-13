"""O motor: áudio -> fala delimitada -> transcrição -> decisão -> navegador.

Cada fala é uma operação com identidade própria (uid). É isso que garante uma única abertura por fala,
mesmo que cheguem vários resultados parciais e finais, e que resultados atrasados de uma captura
pausada ou cancelada sejam jogados fora.
"""

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from voznav.fala import Resultado
from voznav.metricas import Medida, Metricas
from voznav.sessao import Decisao, Sessao

QUADRO = 320  # 20 ms a 16 kHz
MS = 20
PRE_ROLO = 15  # quadros guardados antes do início da fala (300 ms)


@dataclass
class _Fala:
	uid: int
	epoca: int
	modo: str
	quadros: list[np.ndarray] = field(default_factory=list)
	n_voz: int = 0
	t_ultima_voz: float = 0.0
	silencio_ms: int = 0
	t_parcial: float = 0.0
	marca_final: int = -1  # n_voz de quando a transcrição final foi pedida
	resultado: Resultado | None = None
	finalizada: bool = False
	segunda_passada: bool = False
	fim_conhecido: float | None = None  # só em teste com amostra: instante real do fim da fala
	espera: float = 0.0

	def audio(self) -> np.ndarray:
		return np.concatenate(self.quadros) if self.quadros else np.zeros(0, dtype=np.float32)


@dataclass
class _Espera:
	"""Janela de tolerância depois de uma fala: se a pessoa retomar dentro do prazo, pode ser a mesma frase.

	Enquanto a janela existe, o áudio continua sendo anexado à fala original, para que uma eventual junção
	("Abre o YouTube" + pausa + "Music") seja transcrita como um trecho só.
	"""

	fala: _Fala
	prazo: float
	decisao: Decisao | None = None  # preenchida quando a decisão já saiu e está sendo segurada
	t_final: float = 0.0
	t_decidido: float = 0.0
	sucessora: _Fala | None = None  # fala que começou antes de a transcrição da anterior chegar


class Motor:
	def __init__(
		self,
		sessao: Sessao,
		reconhecedor: Any,
		abrir: Callable[[str], None],
		ao_evento: Callable[..., None] | None = None,
		relogio: Callable[[], float] = time.monotonic,
		arquivo_diagnostico: Path | None = None,
	):
		self.sessao, self.reconhecedor, self.abrir = sessao, reconhecedor, abrir
		self.ao_evento = ao_evento or (lambda tipo, **k: None)
		self.relogio = relogio
		self.metricas = Metricas()
		self.arquivo_diagnostico = arquivo_diagnostico
		self.estado = 'pausado'
		self.nivel = 0.0
		self._trava = threading.RLock()
		self._epoca = 0
		self._uid = 0
		self._despachadas: set[int] = set()
		self._fala: _Fala | None = None
		self._espera: _Espera | None = None
		self._ptt = False
		self._resto = np.zeros(0, dtype=np.float32)
		self._pre: deque[np.ndarray] = deque(maxlen=PRE_ROLO)
		self._seguidos = 0
		self._piso = 0.003
		self._fim_conhecido: float | None = None
		# fila do reconhecedor: no máximo uma tarefa final e uma parcial; a final tem prioridade
		self._cond = threading.Condition()
		self._finais: deque[tuple] = deque()
		self._tarefa_parcial: tuple | None = None
		self._ocupado = False
		self._vivo = True
		self._fio = threading.Thread(target=self._laco_reconhecedor, daemon=True)
		self._fio.start()

	# --- configuração lida a cada uso, para valer assim que o usuário muda -----------------------------

	@property
	def _cfg(self):
		return self.sessao.dados.config

	@property
	def modo(self) -> str:
		return self._cfg.modo

	def _estado_ocioso(self) -> str:
		if self.sessao.aguardando:
			return 'escolha'
		return 'ouvindo' if self.modo == 'maos_livres' else 'pronto'

	def _mudar(self, estado: str, **extra) -> None:
		self.estado = estado
		self.ao_evento('estado', estado=estado, **extra)

	# --- controles ---------------------------------------------------------------------------------------

	def ouvir(self) -> None:
		with self._trava:
			self._zerar_captura()
			self._mudar(self._estado_ocioso())

	def pausar(self) -> None:
		"""Pausa e invalida tudo o que estiver em andamento: resultados atrasados não abrem nada."""
		with self._trava:
			self._epoca += 1
			self._zerar_captura()
			self._mudar('pausado')

	def cancelar(self) -> None:
		with self._trava:
			self._epoca += 1
			self._zerar_captura()
			decisao = self.sessao.cancelar()
			self.ao_evento('decisao', decisao=decisao, texto='')
			if self.estado != 'pausado':
				self._mudar(self._estado_ocioso())

	def encerrar(self) -> None:
		self.pausar()
		with self._cond:
			self._vivo = False
			self._cond.notify_all()
		self._fio.join(timeout=3)

	def _zerar_captura(self) -> None:
		self._fala, self._espera, self._ptt = None, None, False
		self._resto = np.zeros(0, dtype=np.float32)
		self._pre.clear()
		self._seguidos = 0
		with self._cond:
			self._finais.clear()
			self._tarefa_parcial = None

	def marcar_fim_conhecido(self, instante: float) -> None:
		"""Só para testes com amostras: informa o instante real em que a fala reproduzida termina."""
		self._fim_conhecido = instante

	# --- pressionar para falar ---------------------------------------------------------------------------

	def pressionar(self) -> None:
		with self._trava:
			if self.estado == 'pausado' or self._ptt or self.modo != 'ptt':
				return
			self._ptt = True
			self._fala = self._nova_fala('ptt')
			self._fala.quadros = list(self._pre)
			self._mudar('ouvindo', parcial='')

	def soltar(self) -> None:
		"""Soltar a tecla é o sinal explícito de fim: não há espera por silêncio."""
		with self._trava:
			if not self._ptt:
				return
			self._ptt = False
			fala, self._fala = self._fala, None
			if fala is None:
				return
			if fala.n_voz * MS < 160:
				self.ao_evento('decisao', decisao=Decisao('repetir', mensagem='Não ouvi nada. Segure a tecla enquanto fala.'), texto='')
				self._mudar(self._estado_ocioso())
				return
			if fala.t_ultima_voz == 0.0:
				fala.t_ultima_voz = self.relogio()
			self._finalizar(fala)

	# --- áudio -------------------------------------------------------------------------------------------

	def alimentar(self, bloco: np.ndarray) -> None:
		"""Recebe áudio mono float32 16 kHz no ritmo em que é capturado."""
		agora = self.relogio()
		with self._trava:
			if self.estado == 'pausado':
				return
			dados = np.concatenate([self._resto, bloco]) if len(self._resto) else bloco
			n = len(dados) // QUADRO
			self._resto = dados[n * QUADRO :]
			for i in range(n):
				self._quadro(dados[i * QUADRO : (i + 1) * QUADRO], agora - (n - 1 - i) * MS / 1000)

	def _nova_fala(self, modo: str) -> _Fala:
		self._uid += 1
		fala = _Fala(uid=self._uid, epoca=self._epoca, modo=modo, t_parcial=self.relogio() - 0.4)
		fala.fim_conhecido, self._fim_conhecido = self._fim_conhecido, None
		return fala

	def _quadro(self, q: np.ndarray, t: float) -> None:
		rms = float(np.sqrt(np.mean(q * q)))
		self.nivel = rms
		fala = self._fala
		limiar = max(0.012, self._piso * 3.5) * (0.7 if fala else 1.0)  # histerese: mais fácil continuar do que começar
		voz = rms > limiar
		if not voz and not fala:
			self._piso = 0.97 * self._piso + 0.03 * rms  # acompanha o ruído de fundo

		if self.modo == 'ptt':
			if fala and self._ptt:
				fala.quadros.append(q)
				if voz:
					fala.n_voz += 1
					fala.t_ultima_voz = t
				self._talvez_parcial(fala, t)
			else:
				self._pre.append(q)
			return

		espera = self._espera
		if espera:
			espera.fala.quadros.append(q)

		if fala is None:
			self._pre.append(q)
			self._seguidos = self._seguidos + 1 if voz else 0
			if self._seguidos >= 4:
				self._seguidos = 0
				if espera and espera.decisao is not None:
					# A frase continuou dentro da tolerância ("YouTube... Music"): mesma fala, nada foi aberto.
					self._espera = None
					fala = espera.fala
					fala.finalizada, fala.silencio_ms, fala.resultado, fala.marca_final = False, 0, None, -1
					fala.n_voz += 4
					fala.t_ultima_voz = t
				else:
					fala = self._nova_fala('maos_livres')
					fala.quadros = list(self._pre)
					fala.n_voz, fala.t_ultima_voz = 4, t
					if espera and espera.sucessora is None and t < espera.prazo:
						espera.sucessora = fala  # a transcrição da anterior ainda não chegou; decide-se quando chegar
				self._fala = fala
				self._mudar('ouvindo', parcial='')
			elif espera and espera.decisao is not None and t >= espera.prazo:
				self._espera = None
				self._despachar(espera.fala, espera.decisao, espera.t_final, espera.t_decidido)
			return

		fala.quadros.append(q)
		if voz:
			fala.n_voz += 1
			fala.t_ultima_voz = t
			fala.silencio_ms = 0
		else:
			fala.silencio_ms += MS
		fim = self._cfg.fim_fala_ms
		if fala.silencio_ms < 160:
			self._talvez_parcial(fala, t)
		elif fala.marca_final != fala.n_voz:
			# Decodificação especulativa: começa a transcrição final antes de o silêncio "fechar". Se a pessoa
			# voltar a falar, o resultado é descartado; se não, a espera pelo silêncio e a decodificação correm juntas.
			self._pedir_final(fala)
		if fala.silencio_ms >= fim or len(fala.quadros) * MS >= 15000:
			self._fala = None
			if fala.n_voz * MS < 160:
				self._mudar(self._estado_ocioso())  # estalo ou batida: curto demais para ser fala
				return
			self._finalizar(fala)

	def _talvez_parcial(self, fala: _Fala, t: float) -> None:
		# Parcial é só para a tela, e disputa o processador com a transcrição final: no máximo uma por segundo.
		if t - fala.t_parcial >= 1.0 and not self._ocupado and fala.n_voz * MS >= 200:
			fala.t_parcial = t
			with self._cond:
				self._tarefa_parcial = (fala, fala.audio(), fala.n_voz, False)
				self._cond.notify()

	def _pedir_final(self, fala: _Fala, preciso: bool = False) -> None:
		fala.marca_final, fala.resultado = fala.n_voz, None
		with self._cond:
			self._finais = deque(f for f in self._finais if f[0] is not fala)  # pedido mais novo da mesma fala substitui o antigo
			self._finais.append((fala, fala.audio(), fala.n_voz, preciso))
			self._tarefa_parcial = None
			self._cond.notify()

	def _finalizar(self, fala: _Fala) -> None:
		fala.finalizada = True
		self._mudar('interpretando')
		tolerancia = self._cfg.espera_extensao_ms
		pendente = self._espera is not None and self._espera.sucessora is fala and self._espera.decisao is None
		if fala.modo == 'maos_livres' and tolerancia > 0 and not pendente:
			# prazo contado a partir do fim acústico da fala, não de quando a transcrição ficou pronta
			self._espera = _Espera(fala, prazo=fala.t_ultima_voz + (self._cfg.fim_fala_ms + tolerancia) / 1000)
		if fala.marca_final != fala.n_voz:
			self._pedir_final(fala)
		elif fala.resultado is not None:
			self._concluir(fala, fala.resultado)
		# senão: a transcrição especulativa já está em andamento e conclui ao chegar

	# --- reconhecedor ------------------------------------------------------------------------------------

	def _laco_reconhecedor(self) -> None:
		while True:
			with self._cond:
				while self._vivo and not (self._finais or self._tarefa_parcial):
					self._cond.wait()
				if not self._vivo:
					return
				final = bool(self._finais)
				if final:
					fala, audio, marca, preciso = self._finais.popleft()
				else:
					fala, audio, marca, preciso = self._tarefa_parcial  # type: ignore[misc]
					self._tarefa_parcial = None
				self._ocupado = True
			try:
				resultado = self.reconhecedor.transcrever(audio, preciso=True) if preciso else self.reconhecedor.transcrever(audio)
			except Exception as erro:
				resultado = Resultado('', False, 0.0)
				self.ao_evento('erro', mensagem=f'Falha no reconhecimento: {erro}')
			try:
				self._chegou(fala, marca, resultado, final)
			finally:
				self._ocupado = False

	def _chegou(self, fala: _Fala, marca: int, resultado: Resultado, final: bool) -> None:
		with self._trava:
			if fala.epoca != self._epoca:
				self.metricas.atrasados_descartados += final
				return
			if not final or not fala.finalizada:
				if final and fala.marca_final == marca:
					fala.resultado = resultado
				if self._fala is fala and resultado.texto:
					self.ao_evento('parcial', texto=resultado.texto)
				return
			if marca != fala.n_voz or marca != fala.marca_final:
				return  # a pessoa voltou a falar depois desse pedido; outro pedido final está a caminho
			self._concluir(fala, resultado)

	def ocioso(self) -> bool:
		"""Nada sendo transcrito nem na fila (usado por testes e pela calibração)."""
		with self._cond:
			return not self._ocupado and not self._finais and not self._tarefa_parcial

	# --- decisão e despacho ------------------------------------------------------------------------------

	def texto_digitado(self, texto: str) -> Decisao:
		"""Comando digitado na janela (ou colado). Passa pelas mesmas regras da fala."""
		with self._trava:
			fala = self._nova_fala('texto')
			fala.finalizada = True
			return self._concluir(fala, Resultado(texto, True, 0.0), segurar=False)

	def _concluir(self, fala: _Fala, resultado: Resultado, segurar: bool = True) -> Decisao | None:
		if fala.epoca != self._epoca:
			self.metricas.atrasados_descartados += 1
			return None
		if fala.uid in self._despachadas:
			self.metricas.duplicatas_bloqueadas += 1  # segundo "final" da mesma fala: ignorado
			return None
		t_final = self.relogio()
		self.ao_evento('final', texto=resultado.texto)
		antes = self.sessao.instantaneo()
		if resultado.confiavel and resultado.texto:
			decisao = self.sessao.processar(resultado.texto)
		else:
			decisao = Decisao('repetir', mensagem='Não entendi. Pode repetir?', via='ruido')
		t_decidido = self.relogio()
		sem_destino = decisao.tipo == 'repetir' or decisao.via == 'busca_nome'
		if sem_destino and not decisao.extensivel and not fala.segunda_passada and fala.quadros and len(fala.quadros) * MS <= 7000:
			# A decodificação rápida (janela curta) não levou a destino nenhum. Antes de pedir para repetir ou de
			# pesquisar um nome estranho, refaz com a janela completa do modelo, que é mais lenta e mais precisa.
			fala.segunda_passada = True
			self.sessao.restaurar(antes)
			self._pedir_final(fala, preciso=True)
			return None
		espera = self._espera if self._espera is not None and self._espera.fala is fala else None
		if espera and segurar and decisao.extensivel:
			# O que foi dito é o começo de outro nome ("YouTube" -> "YouTube Music") ou termina pendurado ("abre o").
			seguinte = espera.sucessora
			if seguinte is not None and seguinte.uid not in self._despachadas and seguinte.epoca == self._epoca:
				# A pessoa já retomou: junta as duas partes numa fala só e transcreve de novo. Nada é aberto agora.
				self.sessao.restaurar(antes)
				self._espera = None
				self._despachadas.add(fala.uid)
				seguinte.quadros = list(fala.quadros)
				seguinte.n_voz += fala.n_voz
				seguinte.fim_conhecido = seguinte.fim_conhecido or fala.fim_conhecido
				seguinte.resultado, seguinte.marca_final = None, -1
				if seguinte.finalizada:
					self._pedir_final(seguinte)
				return None
			if t_decidido < espera.prazo:
				espera.decisao, espera.t_final, espera.t_decidido = decisao, t_final, t_decidido
				return decisao
		if espera:
			self._espera = None
		self._diagnostico(resultado.texto, decisao)
		self._despachar(fala, decisao, t_final, t_decidido)
		return decisao

	def _despachar(self, fala: _Fala, decisao: Decisao, t_final: float, t_decidido: float) -> None:
		if fala.uid in self._despachadas or fala.epoca != self._epoca:
			return
		self._despachadas.add(fala.uid)
		t_inicio_despacho = self.relogio()
		ate_despacho = None
		if decisao.tipo == 'abrir':
			try:
				self.abrir(decisao.url)
				ate_despacho = self.relogio() - t_inicio_despacho
			except Exception as erro:
				decisao = Decisao('repetir', mensagem=f'Não consegui abrir {decisao.url}: {erro}')
		fim = fala.fim_conhecido if fala.fim_conhecido is not None else fala.t_ultima_voz
		com_audio = fala.modo != 'texto'
		self.metricas.registrar(
			Medida(
				modo=fala.modo, resultado=decisao.tipo, via=decisao.via, fim_estimado=fala.fim_conhecido is None,
				fala_ate_final=(t_final - fim) if com_audio else None,
				final_ate_decisao=t_decidido - t_final,
				decisao_ate_despacho=ate_despacho,
				espera_extensao=max(0.0, t_inicio_despacho - t_decidido),
				segunda_passada=fala.segunda_passada,
			)
		)
		self.ao_evento('decisao', decisao=decisao, texto='')
		if decisao.tipo == 'pausar':
			self.pausar()
		elif self.estado != 'pausado':
			self._mudar(self._estado_ocioso())

	def _diagnostico(self, texto: str, decisao: Decisao) -> None:
		"""Só grava se o usuário ligou o diagnóstico: frase reconhecida, decisão e destino."""
		if not (self._cfg.diagnostico and self.arquivo_diagnostico):
			return
		try:
			self.arquivo_diagnostico.parent.mkdir(parents=True, exist_ok=True)
			linha = {'quando': time.strftime('%Y-%m-%d %H:%M:%S'), 'frase': texto, 'decisao': decisao.tipo, 'via': decisao.via, 'destino': decisao.url or decisao.mensagem}
			with self.arquivo_diagnostico.open('a', encoding='utf-8') as arq:
				arq.write(json.dumps(linha, ensure_ascii=False) + '\n')
		except OSError:
			pass
