from pathlib import Path

from projef_mcp.parser import num, parse_pdf

PDF = (Path(__file__).parent / "fixtures" / "repeticao-indebito.pdf").read_bytes()


def test_num():
    assert num("1.234,56") == 1234.56
    assert num("63,8700%") == 63.87
    assert num("-") is None


def test_resumo_e_total():
    d = parse_pdf(PDF)
    assert d["identificador"] == "544240e0"
    assert d["total_da_conta"] == {"data_base": "11/2026", "valor": 9540.85}
    assert d["resumo_partes"] == [{
        "nome": "CONTRIBUINTE TESTE LTDA", "principal_corrigido": 5300.75,
        "juros": 0.0, "selic": 3372.75, "total": 8673.5}]
    assert d["total_sucumbencias"] == 867.35
    assert "Repetição de Indébito" in d["criterios"]


def test_parcelas():
    dem = parse_pdf(PDF)["demonstrativo_parcelas"]
    assert len(dem) == 1 and dem[0]["parte"] == "CONTRIBUINTE TESTE LTDA"
    p = dem[0]["parcelas"]
    assert [x["data"] for x in p] == ["03/21", "04/21", "05/21"]
    assert p[0]["principal"] == 1500.0
    assert p[0]["selic_pct"] == 63.87
    assert p[0]["selic_valor"] == 958.05
    assert p[0]["total"] == 2458.05
    assert round(sum(x["total"] for x in p), 2) == dem[0]["total"] == 8673.5


def test_honorarios_texto():
    d = parse_pdf(PDF)
    assert "art. 85" in d["resumo_sucumbencias"][0]["descricao"]
    assert "Faixa em Salários-mínimos" in d["demonstrativo_honorarios_texto"]
