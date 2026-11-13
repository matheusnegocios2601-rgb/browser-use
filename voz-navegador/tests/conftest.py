import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voznav.dados import Dados
from voznav.sessao import Sessao


@pytest.fixture
def dados(tmp_path):
	d = Dados(tmp_path / 'dados')
	d.gravar_atalho('painel', 'https://app.exemplo.com/vendas/painel?periodo=30d&aba=2#resumo', descricao='acompanhar vendas do mês')
	d.gravar_atalho('Banco do Brasil', 'https://www.bb.com.br/pbb/pagina-inicial')
	d.gravar_atalho('Banco Inter', 'https://internetbanking.bancointer.com.br/')
	return d


@pytest.fixture
def sessao(dados):
	return Sessao(dados)
