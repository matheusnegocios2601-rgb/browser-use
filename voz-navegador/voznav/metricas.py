"""Medições de latência com relógio monotônico. Guarda números, não transcrições."""

import math
from dataclasses import dataclass, field


@dataclass
class Medida:
	modo: str  # 'maos_livres' | 'ptt' | 'texto'
	resultado: str  # tipo da decisão
	via: str
	fim_estimado: bool  # True = fim acústico estimado pelo detector; False = conhecido (amostra de teste)
	fala_ate_final: float | None  # fim acústico da fala -> transcrição final (inclui espera por silêncio)
	final_ate_decisao: float
	decisao_ate_despacho: float | None
	espera_extensao: float = 0.0  # tempo segurado de propósito esperando a frase continuar
	segunda_passada: bool = False  # precisou refazer a transcrição com a janela maior

	@property
	def total(self) -> float | None:
		if self.fala_ate_final is None or self.decisao_ate_despacho is None:
			return None
		return self.fala_ate_final + self.final_ate_decisao + self.espera_extensao + self.decisao_ate_despacho


def percentil(valores: list[float], p: float) -> float | None:
	"""Percentil pelo método do posto mais próximo (sem interpolar: com poucas amostras, interpolar engana)."""
	if not valores:
		return None
	ordenados = sorted(valores)
	return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


@dataclass
class Metricas:
	medidas: list[Medida] = field(default_factory=list)
	inicializacao_s: float | None = None
	duplicatas_bloqueadas: int = 0
	atrasados_descartados: int = 0

	def registrar(self, m: Medida) -> None:
		self.medidas.append(m)

	def resumo(self) -> dict:
		aberturas = [m for m in self.medidas if m.resultado == 'abrir']
		totais = [m.total for m in aberturas if m.total is not None]

		def faixa(vals: list[float]) -> dict:
			return {'n': len(vals), 'mediana_ms': _ms(percentil(vals, 50)), 'p95_ms': _ms(percentil(vals, 95))}

		return {
			'inicializacao_s': self.inicializacao_s,
			'pedidos': len(self.medidas),
			'aberturas': len(aberturas),
			'pedidos_de_repeticao': sum(m.resultado == 'repetir' for m in self.medidas),
			'perguntas_de_escolha': sum(m.resultado == 'escolher' for m in self.medidas),
			'duplicatas_bloqueadas': self.duplicatas_bloqueadas,
			'atrasados_descartados': self.atrasados_descartados,
			'fim_da_fala_ate_despacho': faixa(totais),
			'dentro_de_1s': sum(t <= 1.0 for t in totais),
			'aberturas_com_segunda_passada': sum(m.segunda_passada for m in aberturas),
			'sem_segunda_passada': faixa([m.total for m in aberturas if m.total is not None and not m.segunda_passada]),
			'fala_ate_transcricao_final': faixa([m.fala_ate_final for m in aberturas if m.fala_ate_final is not None]),
			'transcricao_ate_decisao': faixa([m.final_ate_decisao for m in aberturas]),
			'decisao_ate_despacho': faixa([m.decisao_ate_despacho for m in aberturas if m.decisao_ate_despacho is not None]),
			'fim_acustico': 'estimado pelo detector' if any(m.fim_estimado for m in aberturas) else 'conhecido',
		}


def _ms(v: float | None) -> float | None:
	return None if v is None else round(v * 1000, 1)
