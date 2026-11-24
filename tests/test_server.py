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
