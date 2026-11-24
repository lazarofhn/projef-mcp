"""Teste de ponta a ponta contra o Projef Web real. Só roda com PROJEF_ONLINE=1."""
import os

import pytest

from projef_mcp.engine import Calculo, Honorarios, Parcela, Parte, ProjefEngine, baixar_pdf
from projef_mcp.parser import parse_pdf

pytestmark = [pytest.mark.online,
              pytest.mark.skipif(os.environ.get("PROJEF_ONLINE") != "1", reason="defina PROJEF_ONLINE=1")]


async def test_repeticao_indebito_ponta_a_ponta():
    eng = ProjefEngine()
    try:
        r = await eng.calcular(Calculo(
            criterio_correcao=3, data_atualizacao="11/2026", operador="teste automatizado projef-mcp",
            partes=[Parte(nome="CONTRIBUINTE TESTE LTDA", cpf_cnpj="11.222.333/0001-81",
                          parcelas=[Parcela("03/2021", 1500), Parcela("04/2021", 2000.5)])],
            honorarios=Honorarios(modo="3", escalonar_fazenda=True, faixas=[10, 8, 5, 3, 1])))
    finally:
        await eng.close()
    d = parse_pdf(await baixar_pdf(r["identificador"]))
    assert d["identificador"] == r["identificador"]
    assert d["total_partes"]["principal_corrigido"] == 3500.5
    assert d["total_da_conta"]["valor"] > 3500.5
