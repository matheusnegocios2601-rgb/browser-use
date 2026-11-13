"""Tecla global de pressionar-para-falar. Observa o teclado sem bloquear as teclas para os outros programas."""

from collections.abc import Callable

ROTULOS = {
	'ctrl_r': 'Ctrl direito', 'ctrl_l': 'Ctrl esquerdo', 'ctrl': 'Ctrl', 'alt_l': 'Alt esquerdo', 'alt_r': 'Alt direito', 'alt_gr': 'AltGr',
	'shift': 'Shift', 'shift_l': 'Shift esquerdo', 'shift_r': 'Shift direito', 'space': 'Espaço', 'cmd': 'Windows', 'cmd_r': 'Windows direito',
	'caps_lock': 'Caps Lock', 'scroll_lock': 'Scroll Lock', 'pause': 'Pause', 'insert': 'Insert', 'menu': 'Menu',
}


def rotulo(combinacao: str) -> str:
	return ' + '.join(ROTULOS.get(p, p.upper() if len(p) <= 3 else p.capitalize()) for p in combinacao.split('+'))


def _nome(tecla) -> str:
	nome = getattr(tecla, 'name', None)
	if nome:
		return nome
	caractere = getattr(tecla, 'char', None)
	if caractere and caractere.isprintable():
		return caractere.lower()
	return f'vk{getattr(tecla, "vk", 0)}'


class TeclaGlobal:
	def __init__(self, combinacao: str, ao_pressionar: Callable[[], None], ao_soltar: Callable[[], None]):
		self.partes = set(combinacao.split('+'))
		self.ao_pressionar, self.ao_soltar = ao_pressionar, ao_soltar
		self._apertadas: set[str] = set()
		self._ativa = False
		self._ouvinte = None

	def iniciar(self) -> None:
		from pynput import keyboard  # importado aqui: precisa de ambiente gráfico

		self._ouvinte = keyboard.Listener(on_press=self._desce, on_release=self._sobe)
		self._ouvinte.daemon = True
		self._ouvinte.start()

	def parar(self) -> None:
		if self._ouvinte:
			self._ouvinte.stop()
			self._ouvinte = None
		if self._ativa:
			self._ativa = False
			self.ao_soltar()

	def _desce(self, tecla) -> None:
		self._apertadas.add(_nome(tecla))
		if not self._ativa and self.partes <= self._apertadas:
			self._ativa = True
			self.ao_pressionar()

	def _sobe(self, tecla) -> None:
		nome = _nome(tecla)
		self._apertadas.discard(nome)
		if self._ativa and nome in self.partes:
			self._ativa = False
			self.ao_soltar()


def capturar_combinacao(ao_capturar: Callable[[str], None]) -> None:
	"""Espera o usuário apertar e soltar uma tecla (ou combinação) e devolve o nome dela."""
	from pynput import keyboard

	apertadas: list[str] = []

	def desce(tecla) -> None:
		nome = _nome(tecla)
		if nome not in apertadas:
			apertadas.append(nome)

	def sobe(tecla):
		if apertadas:
			ao_capturar('+'.join(apertadas[:3]))
			return False
		return None

	ouvinte = keyboard.Listener(on_press=desce, on_release=sobe)
	ouvinte.daemon = True
	ouvinte.start()
