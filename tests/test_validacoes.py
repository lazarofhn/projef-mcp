import pytest

from projef_mcp.engine import (Calculo, Parcela, Parte, ProjefEngine, ProjefErro, br_num,
                               cpf_cnpj_valido, mmaaaa, numero_cnj_valido)


@pytest.mark.parametrize("entrada,saida", [
    (1000, "1000,00"), (1500.25, "1500,25"), ("1.234,56", "1234,56"), ("R$ 2.000,5", "2000,50"),
    ("1234.5", "1234,50"), (None, "0"),
])
def test_br_num(entrada, saida):
    assert br_num(entrada) == saida


@pytest.mark.parametrize("entrada,saida", [
    ("3/2021", "03/2021"), ("03-2021", "03/2021"), ("2021-03", "03/2021"), ("2021-03-15", "03/2021"),
    ("15/03/2021", "03/2021"),
])
def test_mmaaaa(entrada, saida):
    assert mmaaaa(entrada, "x") == saida


def test_mmaaaa_invalida():
    with pytest.raises(ProjefErro):
        mmaaaa("13/2021", "x")


def test_cpf_cnpj():
    assert cpf_cnpj_valido("529.982.247-25")
    assert cpf_cnpj_valido("11.222.333/0001-81")
    assert not cpf_cnpj_valido("111.111.111-11")
    assert not cpf_cnpj_valido("529.982.247-24")
    assert not cpf_cnpj_valido("11.222.333/0001-80")


def test_numero_cnj():
    assert numero_cnj_valido("5000001-87.2020.4.04.7100")
    assert not numero_cnj_valido("5000001-88.2020.4.04.7100")


def test_validacao_antes_de_abrir_navegador():
    calc = Calculo(criterio_correcao=3, data_atualizacao="11/2026",
                   partes=[Parte(nome="X", cpf_cnpj="111.111.111-12", parcelas=[Parcela("01/2020", 10)])])
    with pytest.raises(ProjefErro, match="CPF/CNPJ inválido"):
        ProjefEngine()._validar(calc)
