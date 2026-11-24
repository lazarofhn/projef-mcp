import json

from mcp.server.fastmcp import FastMCP

from projef_mcp.engine import ProjefEngine
from projef_mcp.server import registrar_ferramentas


async def test_ferramentas_registradas():
    m = FastMCP("projef-teste")
    registrar_ferramentas(m, ProjefEngine())
    nomes = {t.name for t in await m.list_tools()}
    assert nomes == {"projef_opcoes", "projef_calcular", "projef_recuperar"}


async def test_opcoes():
    m = FastMCP("projef-teste")
    registrar_ferramentas(m, ProjefEngine())
    res = await m.call_tool("projef_opcoes", {})
    dados = res[1] if isinstance(res, tuple) else json.loads(res[0].text)
    ids = {c["id"] for c in dados["criterios_correcao"]}
    assert {3, 65} <= ids


async def test_anotacoes_obrigatorias():
    m = FastMCP("projef-teste")
    registrar_ferramentas(m, ProjefEngine())
    ferramentas = {t.name: t for t in await m.list_tools()}
    for nome, t in ferramentas.items():
        a = t.annotations
        assert a is not None and a.title and t.title, nome
        assert a.readOnlyHint is not None and a.destructiveHint is not None, nome
        assert len(nome) <= 64
    assert ferramentas["projef_calcular"].annotations.readOnlyHint is False
    assert ferramentas["projef_recuperar"].annotations.readOnlyHint is True
    assert ferramentas["projef_opcoes"].annotations.readOnlyHint is True


async def test_esquema_restringe_criterio_e_juros():
    m = FastMCP("projef-teste")
    registrar_ferramentas(m, ProjefEngine())
    calc = {t.name: t for t in await m.list_tools()}["projef_calcular"]
    esquema = json.dumps(calc.inputSchema)
    assert '"enum"' in esquema
    assert 65 in calc.inputSchema["properties"]["criterio_correcao"]["enum"]


def test_resultado_grande_e_reduzido(monkeypatch):
    import projef_mcp.server as srv
    parcelas = [{"n": i, "data": "01/20", "principal": 1000.0, "total": 2000.0, "obs": "x" * 200}
                for i in range(1, 1201)]
    monkeypatch.setattr(srv, "parse_pdf", lambda _pdf: {
        "_texto_integral": "t" * 200_000, "demonstrativo_parcelas": [{"parte": "A", "parcelas": parcelas}]})
    content = srv._resultado(b"%PDF", "abc123", "https://x/relatorio?id=abc123", False, True)
    texto = content[0].text
    assert len(texto) <= srv.LIMITE_CARACTERES
    dados = json.loads(texto)
    assert len(dados["demonstrativo_parcelas"][0]["parcelas"]) == 60
    assert "texto_integral" not in dados and "aviso_truncamento" in dados
