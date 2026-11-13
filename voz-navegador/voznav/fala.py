"""Reconhecimento de fala local com faster-whisper (CTranslate2). O modelo fica carregado a sessão inteira."""

import re
import threading
import zlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from voznav.texto import chave_frase

TAXA = 16000
MODELOS = {'tiny': 74, 'base': 141, 'small': 463}  # tamanho aproximado do download em MB
ORIGEM = 'https://huggingface.co/Systran/faster-whisper-{}'

# Frases que o Whisper inventa quando recebe silêncio ou ruído (vêm das legendas com que foi treinado).
_INVENTADAS = {
	'legendas pela comunidade amara.org', 'legendas pela comunidade amara org', 'obrigado', 'obrigada', 'tchau', 'obrigado por assistir',
	'inscreva-se no canal', 'ate a proxima', 'e ai', 'amara.org', 'legendas', 'musica', 'aplausos',
}
_COMANDOS = 'abre, vai pro, pesquisa, procura, cancelar, pausar escuta, criar atalho, salvar, o primeiro, o segundo, ponto com barra'


@dataclass
class Resultado:
	texto: str
	confiavel: bool
	segundos: float  # tempo de decodificação


class Reconhecedor:
	def __init__(self, modelo: str, pasta: Path, vocabulario: list[str] | None = None, threads: int = 0):
		assert modelo in MODELOS, f'modelo desconhecido: {modelo}'
		self.modelo, self.pasta, self.threads = modelo, Path(pasta), threads
		self._whisper = None
		self._tok = None
		self._prompt_cache: tuple[str, list[int]] | None = None
		self._dica = ''
		self._trava = threading.Lock()
		self.definir_vocabulario(vocabulario or [])

	def definir_vocabulario(self, nomes: list[str]) -> None:
		"""Nomes de serviços e atalhos viram dica para o decodificador: é o que faz "GitHub" não virar "guit rabi".

		Os atalhos do usuário vão por último porque, se a dica passar do limite, o Whisper mantém o final.
		"""
		vistos: list[str] = []
		for n in nomes:
			if n and n not in vistos:
				vistos.append(n)
		nomes_txt = ', '.join(vistos)[-600:]
		self._dica = f'Comandos de voz: {_COMANDOS}. Nomes: {nomes_txt}.'

	def baixado(self) -> bool:
		return any(self.pasta.glob(f'models--Systran--faster-whisper-{self.modelo}/snapshots/*/model.bin'))

	def carregar(self, progresso: Callable[[str], None] | None = None) -> None:
		"""Carrega o modelo; na primeira vez baixa, informando tamanho, origem e andamento."""
		from faster_whisper import WhisperModel

		self.pasta.mkdir(parents=True, exist_ok=True)
		if not self.baixado():
			total = MODELOS[self.modelo]
			aviso = f'Baixando o modelo de voz "{self.modelo}" (~{total} MB) de {ORIGEM.format(self.modelo)}'
			parar = threading.Event()

			def acompanhar() -> None:
				while not parar.wait(0.5):
					mb = sum(f.stat().st_size for f in self.pasta.rglob('*') if f.is_file()) / 2**20
					if progresso:
						progresso(f'{aviso} — {min(mb, total):.0f}/{total} MB')

			if progresso:
				progresso(aviso)
			fio = threading.Thread(target=acompanhar, daemon=True)
			fio.start()
			try:
				self._whisper = WhisperModel(self.modelo, device='cpu', compute_type='int8', cpu_threads=self.threads, download_root=str(self.pasta))
			finally:
				parar.set()
		else:
			# local_files_only: depois do primeiro preparo, nada de rede.
			self._whisper = WhisperModel(self.modelo, device='cpu', compute_type='int8', cpu_threads=self.threads, download_root=str(self.pasta), local_files_only=True)
		from faster_whisper.tokenizer import Tokenizer

		self._tok = Tokenizer(self._whisper.hf_tokenizer, self._whisper.model.is_multilingual, task='transcribe', language='pt')
		self.transcrever(np.zeros(TAXA // 2, dtype=np.float32))  # aquece: a primeira decodificação é mais lenta

	def transcrever(self, audio: np.ndarray, preciso: bool = False) -> Resultado:
		assert self._whisper is not None, 'chame carregar() antes'
		# Um pouco de silêncio nas pontas evita que a primeira e a última sílaba sejam comidas.
		margem = np.zeros(TAXA // 4, dtype=np.float32)
		audio = np.concatenate([margem, audio.astype(np.float32)[: 28 * TAXA], margem])
		t0 = time.perf_counter()
		duracao = len(audio) / TAXA
		# O Whisper foi feito para janelas de 30 s e gasta o mesmo tempo com 2 s ou 30 s de áudio. Comandos são
		# curtos: uma janela de 8 s decodifica ~3x mais rápido com o mesmo texto (medido). Janelas menores que isso
		# fazem o modelo entrar em repetição, então 8 s é o piso, e se a saída parecer repetitiva refaz com 30 s.
		# `preciso` é a segunda passada, usada só quando a rápida não levou a lugar nenhum: janela de 15 s, que nas
		# medições transcreveu igual à de 30 s pela metade do tempo.
		janela = max(15.0, min(30.0, float(int(duracao) + 2))) if preciso else 8.0 if duracao <= 7.0 else min(30.0, float(int(duracao) + 2))
		with self._trava:
			texto, sem_fala, logprob = self._decodificar(audio, janela)
			if janela < 30.0 and not preciso and (not texto or _repetitivo(texto)):
				texto, sem_fala, logprob = self._decodificar(audio, 30.0)
		inventada = chave_frase(texto) in _INVENTADAS
		# Nenhum destes números é probabilidade calibrada; servem só para barrar o caso grosseiro de ruído puro.
		confiavel = bool(texto) and not inventada and not _repetitivo(texto) and not (sem_fala > 0.6 and logprob < -0.8) and logprob > -1.6
		return Resultado(texto, confiavel, time.perf_counter() - t0)

	def _decodificar(self, audio: np.ndarray, janela: float) -> tuple[str, float, float]:
		w = self._whisper
		alvo = int(janela * TAXA)
		audio = np.concatenate([audio, np.zeros(max(0, alvo - len(audio)), dtype=np.float32)])[:alvo]
		atributos = w.feature_extractor(audio)[:, : int(janela * 100)]
		r = w.model.generate(
			w.encode(atributos), [self._prompt()], beam_size=1, max_length=len(self._prompt()) + 96,
			return_scores=True, return_no_speech_prob=True, suppress_blank=True,
		)[0]
		texto = re.sub(r'\s+', ' ', self._tok.decode(r.sequences_ids[0])).strip()
		return texto, float(r.no_speech_prob), float(r.scores[0]) if r.scores else -9.0

	def _prompt(self) -> list[int]:
		if self._prompt_cache is None or self._prompt_cache[0] != self._dica:
			self._prompt_cache = (self._dica, self._whisper.get_prompt(self._tok, self._tok.encode(' ' + self._dica), without_timestamps=True))
		return self._prompt_cache[1]


def _repetitivo(texto: str) -> bool:
	"""Texto que comprime demais é o modelo repetindo a si mesmo ("YouTube YouTube YouTube...")."""
	bruto = texto.encode('utf-8')
	return len(bruto) > 40 and len(bruto) / len(zlib.compress(bruto)) > 2.4
