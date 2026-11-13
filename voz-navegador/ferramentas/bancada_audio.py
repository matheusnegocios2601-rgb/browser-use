"""Bancada de áudio: reproduz frases SINTETIZADAS (Piper) no ritmo real do áudio, com fim de fala conhecido,
passando pelo motor e pelo reconhecedor de verdade. As aberturas são interceptadas (nenhum navegador abre).

Uso:  python ferramentas/bancada_audio.py --vozes PASTA_DAS_VOZES --modelos PASTA_DOS_MODELOS [--modelo base] [--saida arquivo.json]

Não é voz humana nem microfone: mede o encadeamento inteiro com áudio reproduzível. Para o seu microfone, use a
calibração guiada dentro do app.
"""

import argparse
import json
import sys
import tempfile
import time
import wave
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import unquote_plus, urlsplit

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voznav.dados import Dados  # noqa: E402
from voznav.fala import Reconhecedor  # noqa: E402
from voznav.motor import Motor  # noqa: E402
from voznav.sessao import Sessao  # noqa: E402
from voznav.texto import dobrar  # noqa: E402

TAXA = 16000
YT, YTM = 'https://www.youtube.com/', 'https://music.youtube.com/'
G = 'https://www.google.com/search?q='
PAINEL = 'https://app.exemplo.com/vendas/painel?periodo=30d&aba=2#resumo'


def F(texto: str, tts: str | None = None) -> tuple:
	"""Uma fala. `tts` é a grafia entregue ao sintetizador quando ele não sabe ler um nome em inglês."""
	return ('fala', texto, tts or texto)


# Cada cenário: passos e as URLs que devem ser abertas, na ordem. Entre falas há 1,6 s de silêncio, salvo 'pausa'.
CENARIOS = [
	('abrir serviço, uma palavra', [F('YouTube')], [YT]),
	('abrir coloquial', [F('vai pro YouTube aí')], [YT]),
	('nome composto', [F('YouTube Music')], [YTM]),
	('pausa no meio do nome', [F('Abre o YouTube'), ('pausa', 650), F('Music')], [YTM]),
	('busca em serviço', [F('Procura análise do Galaxy S no YouTube')], ['https://www.youtube.com/results?search_query=análise do Galaxy S']),
	('consulta contendo nome de serviço', [F('Pesquisa por que o YouTube trava no Chrome')], [G + 'por que o YouTube trava no Chrome']),
	('consulta contendo verbo abrir', [F('Pesquisa como abrir o Gmail', 'Pesquisa como abrir o djí-mêiol')], [G + 'como abrir o Gmail']),
	('endereço ditado', [F('Abre github ponto com barra settings', 'Abre guít-râb ponto com barra sétins')], ['https://github.com/settings']),
	('atalho pessoal', [F('Meu painel')], [PAINEL]),
	('atalho pessoal com verbo', [F('Abre meu painel')], [PAINEL]),
	('atalho por descrição', [F('Aquela página que eu salvei pra acompanhar vendas')], [PAINEL]),
	('dois plausíveis + o segundo', [F('Abre meu banco'), F('o segundo')], ['https://bancointer.com.br/']),
	('escolha + cancelar', [F('Abre meu banco'), F('cancelar'), F('o segundo')], []),
	('site desconhecido', [F('Abre o site da Loja Exemplo')], [G + 'Loja Exemplo']),
	('pesquisa não é endereço', [F('Pesquisa o que é ponto de equilíbrio')], [G + 'o que é ponto de equilíbrio']),
	('outro serviço', [F('Abre a Netflix', 'Abre a Nétflics')], ['https://www.netflix.com/']),
	('busca coloquial', [F('Procura receita de bolo de cenoura por favor')], [G + 'receita de bolo de cenoura']),
	('busca em serviço, serviço primeiro', [F('YouTube, procura como limpar teclado mecânico')], ['https://www.youtube.com/results?search_query=como limpar teclado mecânico']),
	('repetição intencional', [F('Abre a Netflix', 'Abre a Nétflics'), F('Abre a Netflix', 'Abre a Nétflics')], ['https://www.netflix.com/'] * 2),
	('dois comandos em sequência', [F('Meu painel'), F('Pesquisa previsão do tempo')], [PAINEL, G + 'previsão do tempo']),
	('correção depois de erro', [F('peinel'), F('Meu painel')], [PAINEL]),
	('silêncio', [('silencio', 4000)], []),
	('ruído constante', [('ruido', 3000)], []),
	('batidas e estalos', [('estalos', 3000)], []),
	('pausar escuta e falar depois', [F('Pausar escuta'), F('YouTube')], []),
]


def comparar(aberta: str, esperada: str) -> str:
	"""'exato', 'aproximado' (mesmo destino; o texto da consulta difere um pouco do falado) ou 'errado'."""
	a, e = (dobrar(unquote_plus(u)).rstrip('.?! ') for u in (aberta, esperada))
	if a == e:
		return 'exato'
	mesmo_lugar = urlsplit(aberta)[:3] == urlsplit(esperada)[:3]
	return 'aproximado' if mesmo_lugar and SequenceMatcher(None, a, e).ratio() >= 0.9 else 'errado'


def carregar_vozes(pasta: Path):
	from piper import PiperVoice

	return {arq.stem: PiperVoice.load(str(arq)) for arq in sorted(pasta.glob('*.onnx'))}


def sintetizar(voz, texto: str, cache: Path, nome_voz: str) -> tuple[np.ndarray, int]:
	"""Devolve (áudio 16 kHz, índice da última amostra de fala). O fim é medido no próprio sinal."""
	arq = cache / f'{nome_voz}-{abs(hash(texto)) % 10**10}.wav'
	if not arq.exists():
		with wave.open(str(arq), 'wb') as w:
			voz.synthesize_wav(texto, w)
	with wave.open(str(arq), 'rb') as w:
		bruto = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
		taxa = w.getframerate()
	n = int(len(bruto) * TAXA / taxa)
	audio = np.interp(np.linspace(0, len(bruto) - 1, n), np.arange(len(bruto)), bruto).astype(np.float32)
	envelope = np.abs(audio)
	acima = np.nonzero(envelope > 0.02 * envelope.max())[0]
	if not len(acima):
		return audio, len(audio)
	# tira o silêncio que o sintetizador põe antes da fala, com limiar baixo e folga para não cortar consoante suave
	comeco = np.nonzero(envelope > 0.004 * envelope.max())[0]
	inicio = max(0, int(comeco[0]) - TAXA // 12)
	return audio[inicio:], int(acima[-1]) - inicio


def ruido(ms: int, tipo: str, rng) -> np.ndarray:
	n = TAXA * ms // 1000
	if tipo == 'silencio':
		return (rng.standard_normal(n) * 0.0004).astype(np.float32)
	if tipo == 'ruido':  # ventilador/ar-condicionado forte
		return (rng.standard_normal(n) * 0.03).astype(np.float32)
	sinal = (rng.standard_normal(n) * 0.0004).astype(np.float32)  # estalos: teclado, batida na mesa
	for inicio in rng.integers(0, n - 2000, size=6):
		sinal[inicio : inicio + 900] += (rng.standard_normal(900) * 0.4 * np.exp(-np.arange(900) / 150)).astype(np.float32)
	return sinal


def executar(args) -> dict:
	rng = np.random.default_rng(7)
	vozes = carregar_vozes(Path(args.vozes))
	assert vozes, 'nenhuma voz .onnx na pasta'
	cache = Path(tempfile.mkdtemp(prefix='voznav-amostras-'))
	resultados = []
	t0 = time.monotonic()
	rec = Reconhecedor(args.modelo, Path(args.modelos))
	rec.carregar(print)
	inicializacao = time.monotonic() - t0
	todas_medidas = []
	duplicatas = 0

	for nome_voz, voz in vozes.items():
		for nome, passos, esperado in CENARIOS:
			pasta = Path(tempfile.mkdtemp(prefix='voznav-dados-'))
			dados = Dados(pasta)
			dados.gravar_atalho('painel', PAINEL, descricao='acompanhar vendas do mês')
			dados.gravar_atalho('Banco do Brasil', 'https://www.bb.com.br/')
			dados.gravar_atalho('Banco Inter', 'https://bancointer.com.br/')
			rec.definir_vocabulario(dados.vocabulario())
			abertas: list[str] = []
			ouvido: list[str] = []
			motor = Motor(Sessao(dados), rec, abertas.append, lambda tipo, **k: ouvido.append(k['texto']) if tipo == 'final' else None)
			motor.ouvir()

			# monta a trilha inteira e os instantes (em amostras) de fim de cada grupo de fala
			trilha = [ruido(600, 'silencio', rng)]
			fins: list[tuple[int, int]] = []  # (amostra em que o grupo começa, amostra do fim da fala)
			pos = len(trilha[0])
			i = 0
			while i < len(passos):
				p = passos[i]
				if p[0] == 'fala':
					inicio_grupo = pos
					while True:
						audio, fim = sintetizar(voz, passos[i][2], cache, nome_voz)
						audio = audio[: fim + 1]
						trilha.append(audio)
						fim_abs = pos + fim
						pos += len(audio)
						if i + 2 < len(passos) and passos[i + 1][0] == 'pausa':
							trilha.append(ruido(passos[i + 1][1], 'silencio', rng))
							pos += len(trilha[-1])
							i += 2
						else:
							break
					fins.append((inicio_grupo, fim_abs))
					trilha.append(ruido(1600, 'silencio', rng))
				else:
					trilha.append(ruido(p[1], p[0], rng))
					trilha.append(ruido(1200, 'silencio', rng))
				pos = sum(len(x) for x in trilha)
				i += 1
			sinal = np.concatenate(trilha)

			inicio = time.monotonic() + 0.05
			prox = 0
			for k in range(0, len(sinal) - 320, 320):
				alvo = inicio + k / TAXA
				espera = alvo - time.monotonic()
				if espera > 0:
					time.sleep(espera)  # ritmo real do áudio: um quadro de 20 ms a cada 20 ms
				if prox < len(fins) and k >= fins[prox][0] - 320:
					motor.marcar_fim_conhecido(inicio + fins[prox][1] / TAXA)
					prox += 1
				motor.alimentar(sinal[k : k + 320])
			limite = time.monotonic() + 3
			while not motor.ocioso() and time.monotonic() < limite:
				time.sleep(0.01)
			time.sleep(0.05)

			certo = len(abertas) == len(esperado) and all(comparar(a, e) != 'errado' for a, e in zip(abertas, esperado))
			exato = len(abertas) == len(esperado) and all(comparar(a, e) == 'exato' for a, e in zip(abertas, esperado))
			medidas = motor.metricas.medidas
			todas_medidas += [m for m in medidas if m.resultado == 'abrir']
			duplicatas += motor.metricas.duplicatas_bloqueadas
			resultados.append({
				'voz': nome_voz, 'cenario': nome, 'acertou': certo, 'exato': exato, 'ouvido': ouvido, 'abriu': abertas, 'esperado': esperado,
				'repeticoes_pedidas': sum(m.resultado == 'repetir' for m in medidas),
				'latencias_ms': [round(m.total * 1000) for m in medidas if m.resultado == 'abrir' and m.total is not None],
				'esperas_extensao_ms': [round(m.espera_extensao * 1000) for m in medidas if m.resultado == 'abrir'],
				'segunda_passada': [m.segunda_passada for m in medidas if m.resultado == 'abrir' and m.total is not None],
			})
			marca = 'ok  ' if exato else 'ok~ ' if certo else 'ERRO'
			print(f'[{marca}] {nome_voz[6:11]:5} {nome:38} ouvido={ouvido} lat={resultados[-1]["latencias_ms"]}', flush=True)
			motor.encerrar()

	from voznav.metricas import Metricas

	geral = Metricas(medidas=todas_medidas, inicializacao_s=round(inicializacao, 2), duplicatas_bloqueadas=duplicatas)
	n = len(resultados)
	aberturas_esperadas = sum(len(r['esperado']) for r in resultados)
	aberturas_feitas = sum(len(r['abriu']) for r in resultados)
	pares = [(a, e) for r in resultados for a, e in zip(r['abriu'], r['esperado'])]
	exatas = sum(comparar(a, e) == 'exato' for a, e in pares)
	certas = sum(comparar(a, e) != 'errado' for a, e in pares)
	resumo = {
		'tipo_de_audio': 'sintetizado (Piper TTS pt-BR), reproduzido em tempo real, fim de fala conhecido',
		'modelo': args.modelo, 'vozes': list(vozes), 'cenarios_executados': n,
		'cenarios_corretos_de_primeira': sum(r['acertou'] for r in resultados),
		'cenarios_exatos_de_primeira': sum(r['exato'] for r in resultados),
		'aberturas_esperadas': aberturas_esperadas, 'aberturas_feitas': aberturas_feitas,
		'aberturas_no_destino_certo': certas, 'das_quais_com_texto_identico': exatas,
		'aberturas_incorretas': aberturas_feitas - certas,
		'pedidos_de_repeticao': sum(r['repeticoes_pedidas'] for r in resultados),
		'latencia': geral.resumo(),
	}
	return {'resumo': resumo, 'cenarios': resultados}


if __name__ == '__main__':
	ap = argparse.ArgumentParser()
	ap.add_argument('--vozes', required=True)
	ap.add_argument('--modelos', required=True)
	ap.add_argument('--modelo', default='small')
	ap.add_argument('--saida')
	args = ap.parse_args()
	saida = executar(args)
	print(json.dumps(saida['resumo'], ensure_ascii=False, indent=2))
	sys.stdout.flush()
	if args.saida:
		Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding='utf-8')
