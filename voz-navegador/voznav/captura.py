"""Captura do microfone com sounddevice, mensagens de erro acionáveis e recuperação sem reiniciar."""

import threading
import time
from collections.abc import Callable

import numpy as np

TAXA = 16000
QUADRO = 320  # 20 ms


class ErroMicrofone(Exception):
	"""Leva a causa provável e o que o usuário pode fazer."""

	def __init__(self, causa: str, acao: str):
		super().__init__(f'{causa} {acao}')
		self.causa, self.acao = causa, acao


def _explicar(erro: Exception) -> ErroMicrofone:
	texto = str(erro).lower()
	if 'no default input' in texto or 'error querying device -1' in texto or 'no input device' in texto:
		return ErroMicrofone('Nenhum microfone encontrado.', 'Conecte um microfone e clique em "Tentar de novo".')
	if 'invalid device' in texto or 'device unavailable' in texto or 'no such device' in texto:
		return ErroMicrofone('O microfone escolhido não está disponível (foi desconectado?).', 'Reconecte ou escolha outro na lista e clique em "Tentar de novo".')
	if 'host error' in texto or 'access' in texto or 'permission' in texto or 'unanticipated' in texto:
		return ErroMicrofone(
			'O Windows recusou o acesso ao microfone: falta permissão ou outro programa o está usando em modo exclusivo.',
			'Abra Configurações > Privacidade e segurança > Microfone e ligue "Permitir que aplicativos da área de trabalho acessem o microfone"; '
			'feche programas que estejam em chamada e clique em "Tentar de novo".',
		)
	return ErroMicrofone(f'Não consegui abrir o microfone ({erro}).', 'Confira se ele aparece em Configurações > Sistema > Som e clique em "Tentar de novo".')


def listar_microfones(atualizar: bool = False) -> list[str]:
	"""Nomes dos dispositivos de entrada. `atualizar` reinicia o PortAudio para enxergar o que foi (des)conectado."""
	import sounddevice as sd

	if atualizar:
		sd._terminate()
		sd._initialize()
	padrao_api = sd.default.hostapi if isinstance(sd.default.hostapi, int) and sd.default.hostapi >= 0 else 0
	nomes: list[str] = []
	for d in sd.query_devices():
		if d['max_input_channels'] > 0 and d['hostapi'] == padrao_api and d['name'] not in nomes:
			nomes.append(d['name'])
	return nomes


class Captura:
	"""Abre o microfone e entrega blocos float32 mono 16 kHz. `parar()` libera o dispositivo de verdade."""

	def __init__(self, ao_audio: Callable[[np.ndarray], None], ao_erro: Callable[[ErroMicrofone], None]):
		self.ao_audio, self.ao_erro = ao_audio, ao_erro
		self._fluxo = None
		self._ultimo = 0.0
		self._vigia: threading.Thread | None = None
		self._ativo = False
		self._taxa = TAXA

	def iniciar(self, dispositivo: str | None = None) -> None:
		import sounddevice as sd

		self.parar()
		try:
			indice = None
			if dispositivo:
				achados = [i for i, d in enumerate(sd.query_devices()) if d['name'] == dispositivo and d['max_input_channels'] > 0]
				if not achados:
					raise ErroMicrofone(f'O microfone "{dispositivo}" não foi encontrado.', 'Reconecte ou escolha outro na lista.')
				indice = achados[0]
			try:
				self._taxa = TAXA
				self._fluxo = sd.InputStream(samplerate=TAXA, channels=1, dtype='float32', blocksize=QUADRO, device=indice, callback=self._bloco)
			except sd.PortAudioError:
				# Alguns dispositivos não aceitam 16 kHz direto: abre na taxa nativa e converte.
				self._taxa = int(sd.query_devices(indice, 'input')['default_samplerate'])
				self._fluxo = sd.InputStream(samplerate=self._taxa, channels=1, dtype='float32', blocksize=self._taxa // 50, device=indice, callback=self._bloco)
			self._fluxo.start()
		except ErroMicrofone:
			raise
		except Exception as erro:  # PortAudioError, ValueError do sounddevice etc.
			self._fluxo = None
			raise _explicar(erro) from erro
		self._ativo, self._ultimo = True, time.monotonic()
		self._vigia = threading.Thread(target=self._vigiar, daemon=True)
		self._vigia.start()

	def _bloco(self, dados, quadros, tempo, status) -> None:
		self._ultimo = time.monotonic()
		mono = dados[:, 0]
		if self._taxa != TAXA:
			n = int(round(len(mono) * TAXA / self._taxa))
			mono = np.interp(np.linspace(0, len(mono) - 1, n), np.arange(len(mono)), mono).astype(np.float32)
		self.ao_audio(mono.copy())

	def _vigiar(self) -> None:
		"""Se o áudio para de chegar (cabo puxado, dispositivo removido), avisa em vez de ficar mudo."""
		while self._ativo:
			time.sleep(0.5)
			if self._ativo and time.monotonic() - self._ultimo > 2.0:
				self._ativo = False
				self._fechar()
				self.ao_erro(ErroMicrofone('O microfone parou de enviar áudio (provavelmente foi desconectado).', 'Reconecte e clique em "Tentar de novo".'))

	def _fechar(self) -> None:
		fluxo, self._fluxo = self._fluxo, None
		if fluxo is not None:
			try:
				fluxo.abort()
				fluxo.close()
			except Exception:
				pass

	def parar(self) -> None:
		self._ativo = False
		self._fechar()

	@property
	def ativo(self) -> bool:
		return self._ativo
