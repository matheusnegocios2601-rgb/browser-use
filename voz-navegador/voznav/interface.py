"""Janela principal e sobreposição. Tudo que vem de outras threads entra por uma fila e é tratado na thread do Tk."""

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from voznav import tecla as mod_tecla
from voznav.abrir import abrir_no_navegador
from voznav.captura import Captura, ErroMicrofone, listar_microfones
from voznav.dados import SERVICOS_PADRAO, Dados
from voznav.fala import MODELOS, ORIGEM, Reconhecedor
from voznav.jev import criar_desempate
from voznav.metricas import percentil
from voznav.motor import Motor
from voznav.sessao import Decisao, Sessao

ESTADOS = {
	'carregando': ('#8a8f98', 'Preparando…'),
	'pausado': ('#8a8f98', 'Pausado'),
	'ouvindo': ('#2fb344', 'Ouvindo'),
	'pronto': ('#3b82f6', 'Pronto (segure a tecla)'),
	'interpretando': ('#f59f00', 'Interpretando…'),
	'escolha': ('#ae3ec9', 'Aguardando escolha'),
	'erro': ('#e03131', 'Problema no microfone'),
}

CALIBRACAO = [
	('abre o YouTube', 'https://www.youtube.com/'),
	('abre o Gmail', 'https://mail.google.com/'),
	('abre o GitHub', 'https://github.com/'),
	('YouTube Music', 'https://music.youtube.com/'),
	('pesquisa previsão do tempo para amanhã', 'google.com/search'),
	('procura receita de bolo no YouTube', 'youtube.com/results'),
	('abre github ponto com barra settings', 'https://github.com/settings'),
	('abre a Netflix', 'https://www.netflix.com/'),
]


class App:
	def __init__(self, dados: Dados, t_inicio: float):
		self.dados, self.t_inicio = dados, t_inicio
		self.fila: queue.Queue = queue.Queue()
		self.motor: Motor | None = None
		self.sessao: Sessao | None = None
		self.captura = Captura(self._audio, lambda erro: self.fila.put(('erro_mic', erro)))
		self.tecla: mod_tecla.TeclaGlobal | None = None
		self.estado = 'carregando'
		self.calibrando: list[tuple[str, str, str, float | None]] | None = None
		self._teste_ate = 0.0

		self.raiz = tk.Tk()
		self.raiz.title('Navegador por Voz')
		self.raiz.geometry('640x720')
		self.raiz.minsize(540, 560)
		self.raiz.protocol('WM_DELETE_WINDOW', self.fechar)
		self._montar_janela()
		self._montar_sobreposicao()
		self._mostrar_estado('carregando', 'Carregando o reconhecimento de voz…')
		threading.Thread(target=self._carregar, daemon=True).start()
		self.raiz.after(40, self._tique)

	# ------------------------------------------------------------------------------------------------
	# preparação
	# ------------------------------------------------------------------------------------------------

	def _carregar(self) -> None:
		try:
			rec = Reconhecedor(self.dados.config.modelo if self.dados.config.modelo in MODELOS else 'small', self.dados.pasta / 'modelos', self.dados.vocabulario())
			rec.carregar(lambda msg: self.fila.put(('progresso', msg)))
			self.fila.put(('pronto', rec))
		except Exception as erro:
			self.fila.put(('falha', f'Não consegui preparar o reconhecimento de voz: {erro}. Na primeira vez é preciso internet para baixar o modelo.'))

	def _pronto(self, rec: Reconhecedor) -> None:
		self.rec = rec
		self.sessao = Sessao(self.dados, desempate=criar_desempate(self.dados.config))
		self.motor = Motor(self.sessao, rec, self._abrir, lambda tipo, **k: self.fila.put((tipo, k)), arquivo_diagnostico=self.dados.pasta / 'diagnostico.jsonl')
		self.motor.metricas.inicializacao_s = round(time.monotonic() - self.t_inicio, 2)
		self._aplicar_tecla()
		self.ouvir()

	def _abrir(self, url: str) -> None:
		if self.calibrando is not None:
			self._cal_url = url  # calibração: registra o destino sem abrir o navegador
			return
		abrir_no_navegador(url)
		if self.dados.config.som and sys.platform == 'win32':
			import winsound

			winsound.MessageBeep(winsound.MB_OK)

	def _audio(self, bloco) -> None:
		if self.motor:
			self.motor.alimentar(bloco)
		self._nivel = float((bloco * bloco).mean() ** 0.5)

	# ------------------------------------------------------------------------------------------------
	# controles
	# ------------------------------------------------------------------------------------------------

	def ouvir(self) -> None:
		if not self.motor:
			return
		try:
			self.captura.iniciar(self.dados.config.microfone)
		except ErroMicrofone as erro:
			self._erro_microfone(erro)
			return
		self.quadro_erro.pack_forget()
		self.motor.ouvir()

	def pausar(self) -> None:
		if self.motor:
			self.motor.pausar()
		self.captura.parar()  # libera o microfone de verdade

	def _erro_microfone(self, erro: ErroMicrofone) -> None:
		if self.motor:
			self.motor.pausar()
		self.captura.parar()
		self.rotulo_erro.config(text=f'{erro.causa}\n{erro.acao}')
		self.quadro_erro.pack(fill='x', padx=12, pady=(0, 8), after=self.quadro_estado)
		self._mostrar_estado('erro', erro.causa)

	def _tentar_de_novo(self) -> None:
		self._atualizar_microfones()
		self.ouvir()

	def _aplicar_tecla(self) -> None:
		if self.tecla:
			self.tecla.parar()
			self.tecla = None
		if self.dados.config.modo != 'ptt' or not self.motor:
			return
		try:
			self.tecla = mod_tecla.TeclaGlobal(self.dados.config.tecla, self.motor.pressionar, self.motor.soltar)
			self.tecla.iniciar()
		except Exception as erro:
			self.var_msg.set(f'Não consegui registrar a tecla global ({erro}). Use o modo mãos livres.')

	def _mudar_modo(self) -> None:
		self.dados.config.modo = self.var_modo.get()
		self.dados.salvar()
		self._aplicar_tecla()
		if self.motor and self.motor.estado != 'pausado':
			self.motor.ouvir()

	def _trocar_tecla(self) -> None:
		self.botao_tecla.config(text='Aperte a nova tecla…')
		if self.tecla:
			self.tecla.parar()
			self.tecla = None
		try:
			mod_tecla.capturar_combinacao(lambda combinacao: self.fila.put(('tecla', combinacao)))
		except Exception as erro:
			self.var_msg.set(f'Captura de tecla indisponível: {erro}')

	def _enviar_texto(self, *_):
		texto = self.entrada.get().strip()
		if not texto or not self.motor or not self.sessao:
			return
		self.entrada.delete(0, 'end')
		p = self.sessao.pendente
		if p and p.tipo in ('criar_url', 'criar_confirma') and ' ' not in texto and '.' in texto:
			self._decisao(self.sessao.informar_endereco(texto))  # endereço colado durante a criação de um atalho
		else:
			self.motor.texto_digitado(texto)

	def fechar(self) -> None:
		try:
			if self.tecla:
				self.tecla.parar()
			self.captura.parar()
			if self.motor:
				self.motor.encerrar()
		finally:
			self.raiz.destroy()

	# ------------------------------------------------------------------------------------------------
	# laço de eventos
	# ------------------------------------------------------------------------------------------------

	def _tique(self) -> None:
		try:
			while True:
				tipo, dado = self.fila.get_nowait()
				self._evento(tipo, dado)
		except queue.Empty:
			pass
		self.barra_nivel['value'] = min(100, getattr(self, '_nivel', 0.0) * 600) if self.captura.ativo else 0
		if self._teste_ate and time.monotonic() > self._teste_ate:
			self._teste_ate = 0.0
			if self.estado in ('pausado', 'erro'):
				self.captura.parar()
				self.var_msg.set('Teste do microfone encerrado.')
		self.raiz.after(40, self._tique)

	def _evento(self, tipo: str, dado) -> None:
		if tipo == 'progresso':
			self._mostrar_estado('carregando', dado)
		elif tipo == 'pronto':
			self._pronto(dado)
		elif tipo == 'falha':
			self._mostrar_estado('erro', dado)
			self.var_msg.set(dado)
		elif tipo == 'erro_mic':
			self._erro_microfone(dado)
		elif tipo == 'erro':
			self.var_msg.set(dado['mensagem'])
		elif tipo == 'tecla':
			self.dados.config.tecla = dado
			self.dados.salvar()
			self.botao_tecla.config(text=f'Tecla: {mod_tecla.rotulo(dado)}  (trocar)')
			self._aplicar_tecla()
		elif tipo == 'estado':
			if dado['estado'] == 'pausado' and self.captura.ativo and not self._teste_ate:
				self.captura.parar()  # "pausar escuta" dito por voz também libera o microfone
			self._mostrar_estado(dado['estado'], '' if 'parcial' in dado else None)
		elif tipo == 'parcial':
			self._mostrar_estado(self.estado, dado['texto'] + '…')
		elif tipo == 'final':
			self.var_frase.set(dado['texto'])
		elif tipo == 'decisao':
			self._decisao(dado['decisao'])

	def _decisao(self, d: Decisao) -> None:
		textos = {'abrir': f'Abrindo: {d.rotulo}', 'pausar': 'Escuta pausada. Clique em Ouvir para voltar.'}
		mensagem = textos.get(d.tipo, d.mensagem)
		if d.oferta:
			mensagem += '\n' + d.oferta
		self.var_msg.set(mensagem)
		self._mostrar_estado(self.motor.estado if self.motor else self.estado, mensagem)
		# painel de confirmação de atalho
		if d.via == 'confirmar_atalho':
			self.var_cnome.set(d.rotulo)
			self.var_curl.set(d.url)
			self.quadro_confirma.pack(fill='x', padx=12, pady=6, after=self.quadro_estado)
		else:
			self.quadro_confirma.pack_forget()
		# botões de escolha
		for filho in self.quadro_escolha.winfo_children():
			filho.destroy()
		if d.tipo == 'escolher':
			for i, (rotulo, _) in enumerate(d.opcoes):
				ttk.Button(self.quadro_escolha, text=f'{i + 1}) {rotulo}', command=lambda n=i + 1: self.motor.texto_digitado(f'opção {n}')).pack(side='left', padx=4)
			ttk.Button(self.quadro_escolha, text='Cancelar', command=self.motor.cancelar).pack(side='left', padx=4)
			self.quadro_escolha.pack(fill='x', padx=12, pady=6, after=self.quadro_estado)
		else:
			self.quadro_escolha.pack_forget()
		if d.via in ('atalho_salvo', 'apelido_salvo'):
			self._listar_atalhos()
			self.rec.definir_vocabulario(self.dados.vocabulario())  # o nome novo já vale nesta sessão
		if d.tipo == 'config':
			self.raiz.deiconify()
			self.raiz.lift()
			self.abas.select(1)
		if self.calibrando is not None:
			self._calibracao_avanca(d)

	# ------------------------------------------------------------------------------------------------
	# sobreposição
	# ------------------------------------------------------------------------------------------------

	def _montar_sobreposicao(self) -> None:
		s = tk.Toplevel(self.raiz)
		s.overrideredirect(True)
		s.attributes('-topmost', True)
		try:
			s.attributes('-alpha', 0.93)
		except tk.TclError:
			pass
		s.configure(bg='#1f2329')
		self.sob_ponto = tk.Label(s, text='●', fg='#8a8f98', bg='#1f2329', font=('Segoe UI', 14))
		self.sob_ponto.pack(side='left', padx=(10, 4), pady=6)
		self.sob_texto = tk.Label(s, text='', fg='#f1f3f5', bg='#1f2329', font=('Segoe UI', 10), justify='left', anchor='w', wraplength=520)
		self.sob_texto.pack(side='left', padx=(0, 12), pady=6)
		for w in (s, self.sob_ponto, self.sob_texto):
			w.bind('<Button-1>', lambda e: (self.raiz.deiconify(), self.raiz.lift()))
		self.sob = s
		s.update_idletasks()
		if sys.platform == 'win32':
			# Não rouba o foco da janela em que o usuário está: WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST.
			try:
				import ctypes

				u32 = ctypes.windll.user32
				hwnd = u32.GetParent(s.winfo_id()) or s.winfo_id()
				u32.SetWindowLongW(hwnd, -20, u32.GetWindowLongW(hwnd, -20) | 0x08000000 | 0x00000080 | 0x00000008)
			except Exception:
				pass
		self._posicionar_sobreposicao()

	def _posicionar_sobreposicao(self) -> None:
		self.sob.update_idletasks()
		largura, altura = self.sob.winfo_reqwidth(), self.sob.winfo_reqheight()
		x = (self.sob.winfo_screenwidth() - largura) // 2
		y = self.sob.winfo_screenheight() - altura - 90
		self.sob.geometry(f'+{x}+{y}')

	def _mostrar_estado(self, estado: str, detalhe: str | None = None) -> None:
		self.estado = estado
		cor, nome = ESTADOS.get(estado, ESTADOS['pausado'])
		if estado == 'pronto':
			nome = f'Pronto — segure {mod_tecla.rotulo(self.dados.config.tecla)}'
		self.sob_ponto.config(fg=cor)
		self.var_estado.set(nome)
		self.rotulo_estado.config(foreground=cor)
		if detalhe is not None:
			self._detalhe = detalhe
		texto = nome + (f'\n{self._detalhe}' if getattr(self, '_detalhe', '') else '')
		self.sob_texto.config(text=texto)
		self._posicionar_sobreposicao()
		if estado in ('pausado', 'erro', 'carregando'):
			self.botao_ouvir.config(text='Ouvir', command=self.ouvir)
		else:
			self.botao_ouvir.config(text='Pausar', command=self.pausar)

	# ------------------------------------------------------------------------------------------------
	# janela principal
	# ------------------------------------------------------------------------------------------------

	def _montar_janela(self) -> None:
		self.var_estado, self.var_msg, self.var_frase = tk.StringVar(), tk.StringVar(), tk.StringVar()
		self.abas = ttk.Notebook(self.raiz)
		self.abas.pack(fill='both', expand=True)
		inicio, atalhos, buscas, opcoes, medicoes = (ttk.Frame(self.abas) for _ in range(5))
		for quadro, nome in ((inicio, 'Início'), (atalhos, 'Atalhos'), (buscas, 'Buscas'), (opcoes, 'Opções'), (medicoes, 'Medições')):
			self.abas.add(quadro, text=nome)
		self._aba_inicio(inicio)
		self._aba_atalhos(atalhos)
		self._aba_buscas(buscas)
		self._aba_opcoes(opcoes)
		self._aba_medicoes(medicoes)

	def _aba_inicio(self, f: ttk.Frame) -> None:
		q = ttk.Frame(f)
		q.pack(fill='x', padx=12, pady=10)
		self.quadro_estado = q
		self.rotulo_estado = ttk.Label(q, textvariable=self.var_estado, font=('Segoe UI', 18, 'bold'))
		self.rotulo_estado.pack(side='left')
		self.botao_ouvir = ttk.Button(q, text='Ouvir', command=self.ouvir)
		self.botao_ouvir.pack(side='right')

		self.quadro_erro = ttk.Frame(f)
		self.rotulo_erro = ttk.Label(self.quadro_erro, foreground='#e03131', wraplength=540, justify='left')
		self.rotulo_erro.pack(anchor='w')
		ttk.Button(self.quadro_erro, text='Tentar de novo', command=self._tentar_de_novo).pack(anchor='w', pady=4)

		self.quadro_escolha = ttk.Frame(f)
		self.quadro_confirma = ttk.LabelFrame(f, text='Novo atalho: confira e corrija antes de salvar')
		self.var_cnome, self.var_curl = tk.StringVar(), tk.StringVar()
		for i, (rot, var) in enumerate((('Nome', self.var_cnome), ('Endereço', self.var_curl))):
			ttk.Label(self.quadro_confirma, text=rot).grid(row=i, column=0, sticky='w', padx=6, pady=3)
			ttk.Entry(self.quadro_confirma, textvariable=var, width=40).grid(row=i, column=1, sticky='we', padx=6, pady=3)
		self.quadro_confirma.columnconfigure(1, weight=1)
		b = ttk.Frame(self.quadro_confirma)
		b.grid(row=2, column=1, sticky='e', padx=6, pady=4)
		ttk.Button(b, text='Salvar', command=lambda: self._decisao(self.sessao.confirmar_atalho(self.var_cnome.get(), self.var_curl.get()))).pack(side='left', padx=3)
		ttk.Button(b, text='Cancelar', command=lambda: self.motor.cancelar()).pack(side='left')

		ttk.Label(f, text='Última frase reconhecida:').pack(anchor='w', padx=12)
		ttk.Label(f, textvariable=self.var_frase, font=('Segoe UI', 11, 'italic'), wraplength=560).pack(anchor='w', padx=12, pady=(0, 6))
		ttk.Label(f, textvariable=self.var_msg, wraplength=560, justify='left').pack(anchor='w', padx=12, pady=(0, 10))

		q = ttk.LabelFrame(f, text='Digitar um comando ou colar um endereço')
		q.pack(fill='x', padx=12, pady=6)
		self.entrada = ttk.Entry(q)
		self.entrada.pack(side='left', fill='x', expand=True, padx=6, pady=6)
		self.entrada.bind('<Return>', self._enviar_texto)
		ttk.Button(q, text='Enviar', command=self._enviar_texto).pack(side='left', padx=6)

		q = ttk.LabelFrame(f, text='Como escutar')
		q.pack(fill='x', padx=12, pady=6)
		self.var_modo = tk.StringVar(value=self.dados.config.modo)
		ttk.Radiobutton(q, text='Mãos livres: fico ouvindo e você fala quando quiser', value='maos_livres', variable=self.var_modo, command=self._mudar_modo).pack(anchor='w', padx=6)
		ttk.Radiobutton(q, text='Pressionar para falar: segure a tecla, fale, solte', value='ptt', variable=self.var_modo, command=self._mudar_modo).pack(anchor='w', padx=6)
		self.botao_tecla = ttk.Button(q, text=f'Tecla: {mod_tecla.rotulo(self.dados.config.tecla)}  (trocar)', command=self._trocar_tecla)
		self.botao_tecla.pack(anchor='w', padx=6, pady=4)

		q = ttk.LabelFrame(f, text='Microfone')
		q.pack(fill='x', padx=12, pady=6)
		self.combo_mic = ttk.Combobox(q, state='readonly')
		self.combo_mic.pack(side='left', fill='x', expand=True, padx=6, pady=6)
		self.combo_mic.bind('<<ComboboxSelected>>', self._escolher_microfone)
		ttk.Button(q, text='Atualizar lista', command=lambda: self._atualizar_microfones(True)).pack(side='left', padx=3)
		ttk.Button(q, text='Testar nível', command=self._testar_microfone).pack(side='left', padx=3)
		self.barra_nivel = ttk.Progressbar(f, maximum=100)
		self.barra_nivel.pack(fill='x', padx=12, pady=(0, 8))
		self._atualizar_microfones()

	def _atualizar_microfones(self, reiniciar: bool = False) -> None:
		try:
			nomes = listar_microfones(atualizar=reiniciar and not self.captura.ativo)
		except Exception:
			nomes = []
		self.combo_mic['values'] = ['(padrão do Windows)', *nomes]
		atual = self.dados.config.microfone
		self.combo_mic.set(atual if atual in nomes else '(padrão do Windows)')

	def _escolher_microfone(self, *_):
		nome = self.combo_mic.get()
		self.dados.config.microfone = None if nome.startswith('(') else nome
		self.dados.salvar()
		if self.captura.ativo:
			self.ouvir()

	def _testar_microfone(self) -> None:
		"""Mostra o nível por 6 s. Se a escuta estiver pausada, abre o microfone só para o teste."""
		if not self.captura.ativo:
			try:
				self.captura.iniciar(self.dados.config.microfone)
			except ErroMicrofone as erro:
				self._erro_microfone(erro)
				return
			self._teste_ate = time.monotonic() + 6
		self.var_msg.set('Fale normalmente: a barra deve passar da metade. Se quase não se mexe, aumente o volume do microfone no Windows.')

	# --- atalhos ---

	def _aba_atalhos(self, f: ttk.Frame) -> None:
		self.lista_atalhos = ttk.Treeview(f, columns=('nome', 'url'), show='headings', height=9)
		self.lista_atalhos.heading('nome', text='Nome')
		self.lista_atalhos.heading('url', text='Endereço')
		self.lista_atalhos.column('nome', width=160)
		self.lista_atalhos.column('url', width=380)
		self.lista_atalhos.pack(fill='both', expand=True, padx=12, pady=10)
		self.lista_atalhos.bind('<<TreeviewSelect>>', self._selecionar_atalho)
		q = ttk.Frame(f)
		q.pack(fill='x', padx=12)
		self.campos_atalho = {}
		for i, (chave, rot) in enumerate((('nome', 'Nome (como você fala)'), ('url', 'Endereço completo'), ('apelidos', 'Outras formas de falar (separe por vírgula)'), ('descricao', 'Descrição (opcional)'))):
			ttk.Label(q, text=rot).grid(row=i, column=0, sticky='w', pady=3)
			e = ttk.Entry(q, width=52)
			e.grid(row=i, column=1, sticky='we', padx=6, pady=3)
			self.campos_atalho[chave] = e
		q.columnconfigure(1, weight=1)
		b = ttk.Frame(f)
		b.pack(fill='x', padx=12, pady=10)
		ttk.Button(b, text='Novo', command=lambda: [e.delete(0, 'end') for e in self.campos_atalho.values()]).pack(side='left')
		ttk.Button(b, text='Salvar', command=self._salvar_atalho).pack(side='left', padx=6)
		ttk.Button(b, text='Remover', command=self._remover_atalho).pack(side='left')
		ttk.Label(f, text='Por voz: diga "criar atalho" e o nome; depois dite ou cole o endereço e diga "salvar".', wraplength=560).pack(anchor='w', padx=12, pady=(0, 10))
		self._listar_atalhos()

	def _listar_atalhos(self) -> None:
		self.lista_atalhos.delete(*self.lista_atalhos.get_children())
		for a in self.dados.atalhos:
			self.lista_atalhos.insert('', 'end', iid=a.nome, values=(a.nome, a.url))

	def _selecionar_atalho(self, *_):
		sel = self.lista_atalhos.selection()
		a = self.dados.achar_atalho(sel[0]) if sel else None
		if a:
			for chave, valor in (('nome', a.nome), ('url', a.url), ('apelidos', ', '.join(a.apelidos)), ('descricao', a.descricao)):
				self.campos_atalho[chave].delete(0, 'end')
				self.campos_atalho[chave].insert(0, valor)

	def _salvar_atalho(self) -> None:
		c = {k: e.get().strip() for k, e in self.campos_atalho.items()}
		from voznav.urls import completar_url

		try:
			url = completar_url(c['url'])
			existente = self.dados.achar_atalho(c['nome'])
			if existente and existente.url != url and not messagebox.askyesno('Substituir atalho', f'"{existente.nome}" hoje abre:\n{existente.url}\n\nSubstituir por:\n{url} ?'):
				return
			atalho = self.dados.gravar_atalho(c['nome'], url, [a.strip() for a in c['apelidos'].split(',') if a.strip()], c['descricao'])
			atalho.descricao = c['descricao']
			self.dados.salvar()
		except ValueError as erro:
			messagebox.showerror('Atalho', str(erro))
			return
		self._listar_atalhos()
		if hasattr(self, 'rec'):
			self.rec.definir_vocabulario(self.dados.vocabulario())

	def _remover_atalho(self) -> None:
		sel = self.lista_atalhos.selection()
		if sel and messagebox.askyesno('Remover', f'Remover o atalho "{sel[0]}"?'):
			self.dados.remover_atalho(sel[0])
			self._listar_atalhos()

	# --- buscas ---

	def _aba_buscas(self, f: ttk.Frame) -> None:
		q = ttk.LabelFrame(f, text='Buscador geral (usado em "pesquisa …")')
		q.pack(fill='x', padx=12, pady=10)
		self.campo_buscador = ttk.Entry(q)
		self.campo_buscador.insert(0, self.dados.config.buscador)
		self.campo_buscador.pack(side='left', fill='x', expand=True, padx=6, pady=6)
		ttk.Button(q, text='Salvar', command=self._salvar_buscador).pack(side='left', padx=6)
		ttk.Label(f, text='O {q} marca onde entra o texto. Ex.: https://duckduckgo.com/?q={q}', wraplength=560).pack(anchor='w', padx=12)

		self.lista_servicos = ttk.Treeview(f, columns=('nome', 'busca'), show='headings', height=8)
		self.lista_servicos.heading('nome', text='Serviço')
		self.lista_servicos.heading('busca', text='Modelo de busca')
		self.lista_servicos.column('nome', width=150)
		self.lista_servicos.column('busca', width=390)
		self.lista_servicos.pack(fill='both', expand=True, padx=12, pady=10)
		self.lista_servicos.bind('<<TreeviewSelect>>', self._selecionar_servico)
		q = ttk.Frame(f)
		q.pack(fill='x', padx=12)
		self.campos_servico = {}
		for i, (chave, rot) in enumerate((('nome', 'Nome'), ('url', 'Página inicial'), ('busca', 'Modelo de busca com {q}'), ('apelidos', 'Outras formas de falar'))):
			ttk.Label(q, text=rot).grid(row=i, column=0, sticky='w', pady=3)
			e = ttk.Entry(q, width=52)
			e.grid(row=i, column=1, sticky='we', padx=6, pady=3)
			self.campos_servico[chave] = e
		q.columnconfigure(1, weight=1)
		b = ttk.Frame(f)
		b.pack(fill='x', padx=12, pady=10)
		ttk.Button(b, text='Salvar serviço', command=self._salvar_servico).pack(side='left')
		ttk.Button(b, text='Remover (só os que você criou ou alterou)', command=self._remover_servico).pack(side='left', padx=6)
		self._listar_servicos()

	def _listar_servicos(self) -> None:
		self.lista_servicos.delete(*self.lista_servicos.get_children())
		for s in self.dados.todos_servicos():
			self.lista_servicos.insert('', 'end', iid=s.nome, values=(s.nome + ('' if s in SERVICOS_PADRAO else '  (seu)'), s.busca or '— só abre —'))

	def _selecionar_servico(self, *_):
		sel = self.lista_servicos.selection()
		s = next((x for x in self.dados.todos_servicos() if sel and x.nome == sel[0]), None)
		if s:
			for chave, valor in (('nome', s.nome), ('url', s.url), ('busca', s.busca or ''), ('apelidos', ', '.join(s.apelidos))):
				self.campos_servico[chave].delete(0, 'end')
				self.campos_servico[chave].insert(0, valor)

	def _salvar_buscador(self) -> None:
		try:
			self.dados.definir_buscador(self.campo_buscador.get())
			self.var_msg.set('Buscador geral atualizado.')
		except ValueError as erro:
			messagebox.showerror('Buscador', str(erro))

	def _salvar_servico(self) -> None:
		c = {k: e.get().strip() for k, e in self.campos_servico.items()}
		from voznav.urls import completar_url

		try:
			self.dados.gravar_servico(c['nome'], completar_url(c['url']), c['busca'] or None, [a.strip() for a in c['apelidos'].split(',') if a.strip()])
		except ValueError as erro:
			messagebox.showerror('Serviço', str(erro))
			return
		self._listar_servicos()
		if hasattr(self, 'rec'):
			self.rec.definir_vocabulario(self.dados.vocabulario())

	def _remover_servico(self) -> None:
		sel = self.lista_servicos.selection()
		if sel and self.dados.remover_servico(sel[0]):
			self._listar_servicos()

	# --- opções ---

	def _aba_opcoes(self, f: ttk.Frame) -> None:
		c = self.dados.config
		q = ttk.LabelFrame(f, text='Reconhecimento (roda neste computador, sem conta)')
		q.pack(fill='x', padx=12, pady=8)
		self.var_modelo = tk.StringVar(value=c.modelo)
		ttk.Label(q, text='Modelo:').grid(row=0, column=0, sticky='w', padx=6, pady=4)
		ttk.Combobox(q, textvariable=self.var_modelo, values=list(MODELOS), state='readonly', width=8).grid(row=0, column=1, sticky='w')
		ttk.Label(q, text='small = mais preciso (~463 MB) · base = mais leve (~141 MB) · tiny = PCs fracos (~74 MB). Vale ao reabrir o app.', wraplength=560).grid(row=3, column=0, columnspan=3, sticky='w', padx=6, pady=(0, 4))
		self.var_fim, self.var_tol = tk.IntVar(value=c.fim_fala_ms), tk.IntVar(value=c.espera_extensao_ms)
		for i, (rot, var, de, ate) in enumerate((('Silêncio que encerra a frase (ms)', self.var_fim, 300, 1200), ('Tolerância extra a pausa no meio de um nome (ms)', self.var_tol, 0, 1000)), start=1):
			ttk.Label(q, text=rot).grid(row=i, column=0, columnspan=2, sticky='w', padx=6, pady=4)
			tk.Scale(q, from_=de, to=ate, resolution=50, orient='horizontal', variable=var, length=200).grid(row=i, column=2, sticky='w', padx=6)

		q = ttk.LabelFrame(f, text='Retorno e privacidade')
		q.pack(fill='x', padx=12, pady=8)
		self.var_som, self.var_diag = tk.BooleanVar(value=c.som), tk.BooleanVar(value=c.diagnostico)
		ttk.Checkbutton(q, text='Som curto ao abrir um destino', variable=self.var_som).pack(anchor='w', padx=6)
		ttk.Checkbutton(q, text='Diagnóstico: gravar em arquivo as frases reconhecidas, a decisão e o destino', variable=self.var_diag).pack(anchor='w', padx=6)
		ttk.Label(q, text=f'Desligado por padrão. Ligado, grava texto (nunca áudio) em:\n{self.dados.pasta / "diagnostico.jsonl"}', wraplength=540, justify='left').pack(anchor='w', padx=6)
		ttk.Button(q, text='Apagar diagnóstico gravado', command=self._apagar_diagnostico).pack(anchor='w', padx=6, pady=4)

		q = ttk.LabelFrame(f, text='Pronúncias → escrita (uma por linha: fala = escrita)')
		q.pack(fill='x', padx=12, pady=8)
		self.texto_pron = tk.Text(q, height=4, width=60)
		self.texto_pron.insert('1.0', '\n'.join(f'{k} = {v}' for k, v in c.pronuncias.items()))
		self.texto_pron.pack(fill='x', padx=6, pady=6)

		q = ttk.LabelFrame(f, text='Jev (TypeSafe AI): desempate opcional em nuvem')
		q.pack(fill='x', padx=12, pady=8)
		self.var_jev, self.var_chave = tk.BooleanVar(value=c.jev_ativo), tk.StringVar(value=c.jev_chave)
		ttk.Checkbutton(q, text='Usar o Jev quando houver dúvida entre atalhos', variable=self.var_jev).pack(anchor='w', padx=6)
		ttk.Label(q, text='Chave da API:').pack(side='left', padx=6, pady=4)
		ttk.Entry(q, textvariable=self.var_chave, show='•', width=40).pack(side='left', pady=4)
		ttk.Label(f, text='O Jev exige conta e internet e recebe a frase dita e os nomes dos atalhos em dúvida. Os comandos comuns nunca passam por ele.', wraplength=560, justify='left').pack(anchor='w', padx=12)
		ttk.Button(f, text='Salvar opções', command=self._salvar_opcoes).pack(anchor='e', padx=12, pady=8)

	def _salvar_opcoes(self) -> None:
		c = self.dados.config
		c.modelo, c.fim_fala_ms, c.espera_extensao_ms = self.var_modelo.get(), self.var_fim.get(), self.var_tol.get()
		c.som, c.diagnostico, c.jev_ativo, c.jev_chave = self.var_som.get(), self.var_diag.get(), self.var_jev.get(), self.var_chave.get().strip()
		pron = {}
		for linha in self.texto_pron.get('1.0', 'end').splitlines():
			if '=' in linha:
				fala, escrita = (p.strip() for p in linha.split('=', 1))
				if fala and escrita:
					pron[fala] = escrita
		c.pronuncias = pron
		self.dados.salvar()
		if self.sessao:
			self.sessao.desempate = criar_desempate(c)
		self.var_msg.set('Opções salvas.')

	def _apagar_diagnostico(self) -> None:
		arq = self.dados.pasta / 'diagnostico.jsonl'
		if arq.exists():
			arq.unlink()
		messagebox.showinfo('Diagnóstico', 'Diagnóstico apagado.')

	# --- medições e calibração ---

	def _aba_medicoes(self, f: ttk.Frame) -> None:
		b = ttk.Frame(f)
		b.pack(fill='x', padx=12, pady=10)
		ttk.Button(b, text='Atualizar', command=self._mostrar_medicoes).pack(side='left')
		ttk.Button(b, text='Calibração guiada (8 frases, ~1 min)', command=self._calibrar).pack(side='left', padx=8)
		self.texto_med = tk.Text(f, height=26, wrap='word')
		self.texto_med.pack(fill='both', expand=True, padx=12, pady=(0, 10))
		self.texto_med.insert('1.0', 'As medições desta sessão aparecem aqui. São só números: nenhuma frase é guardada.\n\nA calibração guiada pede 8 frases, confere se cada uma iria para o destino certo (sem abrir o navegador) e mostra a latência do SEU microfone e do SEU computador.')

	def _mostrar_medicoes(self) -> None:
		if not self.motor:
			return
		r = self.motor.metricas.resumo()
		t = r['fim_da_fala_ate_despacho']
		linhas = [
			f'Modelo de voz: {self.dados.config.modelo} ({ORIGEM.format(self.dados.config.modelo)})',
			f'Inicialização até pronto para ouvir: {r["inicializacao_s"]} s',
			f'Pedidos: {r["pedidos"]}  ·  aberturas: {r["aberturas"]}  ·  pedidos de repetição: {r["pedidos_de_repeticao"]}  ·  perguntas de escolha: {r["perguntas_de_escolha"]}',
			f'Duplicatas bloqueadas: {r["duplicatas_bloqueadas"]}  ·  resultados atrasados descartados: {r["atrasados_descartados"]}',
			'',
			f'Fim da fala → despacho da URL ao Windows (n={t["n"]}): mediana {t["mediana_ms"]} ms · p95 {t["p95_ms"]} ms · dentro de 1 s: {r["dentro_de_1s"]}/{t["n"]}',
			f'  das quais {r["aberturas_com_segunda_passada"]} precisaram de segunda passada; sem elas: mediana {r["sem_segunda_passada"]["mediana_ms"]} ms · p95 {r["sem_segunda_passada"]["p95_ms"]} ms',
			f'  fim da fala → transcrição final (inclui espera por silêncio): mediana {r["fala_ate_transcricao_final"]["mediana_ms"]} ms · p95 {r["fala_ate_transcricao_final"]["p95_ms"]} ms',
			f'  transcrição final → escolha do destino: mediana {r["transcricao_ate_decisao"]["mediana_ms"]} ms',
			f'  escolha do destino → despacho: mediana {r["decisao_ate_despacho"]["mediana_ms"]} ms',
			'',
			f'Fim acústico da fala: {r["fim_acustico"]} (ao vivo é uma estimativa do detector de voz).',
			'Despacho = momento em que a URL foi entregue ao Windows. O carregamento da página vem depois e não é medido aqui.',
		]
		self.texto_med.delete('1.0', 'end')
		self.texto_med.insert('1.0', '\n'.join(linhas))

	def _calibrar(self) -> None:
		if not self.motor or self.estado in ('pausado', 'erro', 'carregando'):
			messagebox.showinfo('Calibração', 'Clique em Ouvir primeiro (o microfone precisa estar funcionando).')
			return
		self.calibrando, self._cal_url = [], ''
		self._cal_n = len(self.motor.metricas.medidas)
		self._calibracao_pede()

	def _calibracao_pede(self) -> None:
		i = len(self.calibrando)
		frase = CALIBRACAO[i][0]
		instrucao = f'Calibração {i + 1}/{len(CALIBRACAO)} — diga:  «{frase}»'
		if self.dados.config.modo == 'ptt':
			instrucao += f'   (segurando {mod_tecla.rotulo(self.dados.config.tecla)})'
		self.var_msg.set(instrucao)
		self._mostrar_estado(self.estado, instrucao)
		self.texto_med.delete('1.0', 'end')
		self.texto_med.insert('1.0', instrucao + '\n\nNada será aberto durante a calibração.')

	def _calibracao_avanca(self, d: Decisao) -> None:
		assert self.calibrando is not None and self.motor
		frase, esperado = CALIBRACAO[len(self.calibrando)]
		url, self._cal_url = self._cal_url, ''
		medidas = self.motor.metricas.medidas[self._cal_n :]
		self._cal_n = len(self.motor.metricas.medidas)
		total = medidas[-1].total if medidas and d.tipo == 'abrir' else None
		self.calibrando.append((frase, self.var_frase.get(), url if d.tipo == 'abrir' else f'({d.tipo})', total))
		if len(self.calibrando) < len(CALIBRACAO):
			self._calibracao_pede()
			return
		resultado, self.calibrando = self.calibrando, None
		certos = sum(esp in url for (_, _, url, _), (_, esp) in zip(resultado, CALIBRACAO))
		tempos = [t for *_, t in resultado if t is not None]
		linhas = [f'CALIBRAÇÃO — microfone e voz reais, modo {"mãos livres" if self.dados.config.modo == "maos_livres" else "pressionar para falar"}, modelo {self.dados.config.modelo}', '']
		for (frase, ouvido, url, t), (_, esp) in zip(resultado, CALIBRACAO):
			linhas.append(f'{"✔" if esp in url else "✘"} pedi «{frase}» · ouvi «{ouvido}» · destino {url} · {"—" if t is None else f"{t * 1000:.0f} ms"}')
		linhas += ['', f'Destino certo de primeira: {certos}/{len(CALIBRACAO)}']
		if tempos:
			linhas.append(f'Fim da fala → despacho (n={len(tempos)}): mediana {percentil(tempos, 50) * 1000:.0f} ms · p95 {percentil(tempos, 95) * 1000:.0f} ms · dentro de 1 s: {sum(t <= 1 for t in tempos)}/{len(tempos)}')
		linhas += ['O fim da fala aqui é ESTIMADO pelo detector de voz (ao vivo não há como conhecê-lo exatamente).', '"YouTube" sozinho espera de propósito a tolerância de pausa, porque pode virar "YouTube Music".']
		if tempos and percentil(tempos, 95) > 1.0:
			linhas.append('Passou de 1 s: em Opções, experimente o modelo "base", ou use pressionar para falar (não espera silêncio).')
		self.texto_med.delete('1.0', 'end')
		self.texto_med.insert('1.0', '\n'.join(linhas))
		self.var_msg.set('Calibração concluída: veja a aba Medições.')
		self.abas.select(4)

	def executar(self) -> None:
		self.raiz.mainloop()


def iniciar(t_inicio: float, pasta: Path | None = None) -> None:
	App(Dados(pasta), t_inicio).executar()
