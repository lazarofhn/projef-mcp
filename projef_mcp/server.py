"""Servidor MCP do Projef Web (calculadora judicial da JFRS).

Local (Claude Desktop, stdio):  projef-mcp            (ou: python -m projef_mcp)
Remoto (streamable HTTP):       projef-mcp --http [--host 127.0.0.1] [--port 8092]

Variáveis de ambiente do modo remoto:
  PROJEF_PATH_SECRET    segmento secreto no caminho -> https://host/<segredo>/mcp
  PROJEF_ALLOWED_HOSTS  hosts aceitos no cabeçalho Host, separados por vírgula
  PROJEF_CONCORRENCIA   cálculos simultâneos (padrão 2)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent
from pydantic import BaseModel, Field

from projef_mcp import engine as E
from projef_mcp.opcoes import CRITERIOS_CORRECAO, HONORARIOS_MODOS, JUROS, ORIENTACAO, UFS
from projef_mcp.parser import parse_pdf

INSTRUCOES = f"""\
Calcula débitos judiciais no Projef Web (JFRS), o mesmo programa do site
https://www.jfrs.jus.br/projefweb/. O cálculo é feito pelo servidor da JFRS; este MCP preenche o
formulário, devolve os números estruturados e o link oficial do PDF (relatorio?id=...), que pode
ser aberto por qualquer pessoa e vale por 3 anos.

Sempre entregue ao usuário o link url_pdf como link clicável e o identificador. Resuma o total da
conta, a composição (principal corrigido, juros, Selic, honorários) e, se pedido, a tabela por
parcela. Não invente critério: se o usuário não disser, pergunte ou use a orientação abaixo
deixando claro o critério adotado.

{ORIENTACAO}"""

mcp: FastMCP  # definido em main()


class ParcelaIn(BaseModel):
    data: Annotated[str, Field(description="Mês/ano da parcela (recolhimento ou vencimento), mm/aaaa")]
    principal: Annotated[float | str, Field(description="Valor nominal (ex.: 1500.25 ou '1.500,25')")]
    juros: Annotated[float | str | None, Field(description="Juros já apurados, se houver (raro)")] = None
    selic: Annotated[float | str | None, Field(description="Selic já apurada, se houver (raro)")] = None


class ParteIn(BaseModel):
    nome: str
    cpf_cnpj: Annotated[str, Field(description="CPF ou CNPJ válido (o Projef confere os dígitos)")]
    parcelas: list[ParcelaIn]
    honorarios_contratuais_percentual: Annotated[float | None, Field(
        description="Destaque de honorários contratuais (%), opcional")] = None
    honorarios_contratuais_cpf_cnpj: str | None = None


class HonorariosIn(BaseModel):
    modo: Annotated[Literal["0", "1", "2", "3", "4", "5"], Field(
        description="0 nenhum; 3 valor da condenação; 1 valor da causa/proveito econômico; 2 valor certo; "
                    "4 condenação sem descontos; 5 condenação com descontos até considerar_ate")] = "3"
    escalonar_fazenda: Annotated[bool, Field(
        description="Escalonar pelas faixas do art. 85, §3º, CPC (Fazenda Pública parte)")] = False
    faixas: Annotated[list[float] | None, Field(
        description="Percentuais das 5 faixas do §3º quando escalonar_fazenda=true, ex. [10,8,5,3,1]")] = None
    percentual: Annotated[float | None, Field(description="Percentual único (quando não escalona)")] = None
    cpf_cnpj: Annotated[str | None, Field(description="CPF/CNPJ do advogado/sociedade beneficiário")] = None
    considerar_ate: Annotated[str | None, Field(description="mm/aaaa: parcelas consideradas até (modo 5)")] = None
    valor: Annotated[float | str | None, Field(description="Valor da causa/proveito ou valor certo (modos 1 e 2)")] = None
    data: Annotated[str | None, Field(description="mm/aaaa do valor (modos 1 e 2)")] = None
    data_inicio_juros: Annotated[str | None, Field(description="mm/aaaa início dos juros dos honorários")] = None
    minimo: float | None = None
    maximo: float | None = None
    correcao_manual_cap4: Annotated[bool | None, Field(
        description="Corrigir honorários pelo critério do Cap. 4 do Manual (Ações Condenatórias em Geral)")] = None


def _resultado(pdf: bytes, ident: str, url: str, incluir_pdf: bool, incluir_texto: bool):
    dados = parse_pdf(pdf)
    texto = dados.pop("_texto_integral")
    if incluir_texto:
        dados["texto_integral"] = texto
    payload = {"identificador": ident, "url_pdf": url, **dados}
    content: list = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=1))]
    if incluir_pdf:
        content.append(EmbeddedResource(type="resource", resource=BlobResourceContents(
            uri=url, mimeType="application/pdf", blob=base64.b64encode(pdf).decode())))
    return content


def registrar_ferramentas(m: FastMCP, eng: E.ProjefEngine) -> None:

    @m.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def projef_opcoes() -> dict:
        """Lista os códigos aceitos pelo Projef: critérios de correção monetária, taxas de juros
        moratórios, modos de honorários e UFs, com orientação para repetição de indébito e ações
        condenatórias em geral. Consulte antes de calcular se o critério não estiver claro."""
        return {
            "criterios_correcao": [{"id": i, "descricao": d} for i, d in CRITERIOS_CORRECAO],
            "juros_moratorios": [{"codigo": c, "descricao": d} for c, d in JUROS],
            "honorarios_modos": [{"codigo": c, "descricao": d} for c, d in HONORARIOS_MODOS],
            "ufs": UFS,
            "orientacao": ORIENTACAO,
        }

    @m.tool(annotations={"readOnlyHint": False, "openWorldHint": True})
    async def projef_calcular(
        criterio_correcao: Annotated[int, Field(description="id do critério (projef_opcoes). 3 = repetição de "
                                                            "indébito tributário; 65 = condenatórias em geral 2022")],
        data_atualizacao: Annotated[str, Field(description="Data-base da atualização, mm/aaaa")],
        partes: Annotated[list[ParteIn], Field(description="Credores com suas parcelas")],
        selic_ec113: Annotated[bool, Field(description="Selic a partir de 12/2021 (EC 113/21)")] = False,
        selic_citacao: Annotated[bool, Field(description="Selic a partir da citação")] = False,
        permitir_deflacao: bool = False,
        juros_codigo: Annotated[str, Field(description="Código da taxa de juros (projef_opcoes); '0' sem juros")] = "0",
        juros_data_inicio: Annotated[str | None, Field(description="Início dos juros, mm/aaaa (ex.: citação)")] = None,
        honorarios: Annotated[HonorariosIn | None, Field(description="Honorários sucumbenciais")] = None,
        numero_processo: Annotated[str | None, Field(description="Número CNJ (opcional)")] = None,
        autor: str | None = None,
        reu: str | None = None,
        percentual_acordo: Annotated[float | None, Field(description="Percentual de acordo (30 a 100)")] = None,
        rra: Annotated[bool, Field(description="Parcelas são Rendimentos Recebidos Acumuladamente (art. 12-A, Lei 7.713/88)")] = False,
        gerar_sicar: Annotated[bool, Field(description="Gerar demonstrativo SICAR-JF4R (consulta o processo no "
                                                       "eproc da 4ª Região e preenche autor/réu reais)")] = False,
        operador: Annotated[str | None, Field(description="Confeccionador do cálculo")] = None,
        instituicao: str | None = None,
        cidade: str | None = None,
        uf: str | None = None,
        observacoes: str | None = None,
        incluir_pdf: Annotated[bool, Field(description="Anexar o PDF à resposta (além do link)")] = False,
        incluir_texto: Annotated[bool, Field(description="Incluir o texto integral do demonstrativo")] = False,
    ):
        """Faz um cálculo judicial no Projef Web da JFRS (correção monetária, juros/Selic e honorários
        sobre parcelas) e devolve: identificador, link oficial do PDF (url_pdf), resumo por parte,
        sucumbências, total da conta, critérios aplicados e o demonstrativo parcela a parcela
        (principal, coeficiente, principal corrigido, juros, Selic %, Selic R$, total).
        Leva de 15 a 40 segundos. Cada cálculo fica gravado no servidor da JFRS por 3 anos."""
        hon = None
        if honorarios and honorarios.modo != "0":
            hon = E.Honorarios(**honorarios.model_dump())
        calc = E.Calculo(
            criterio_correcao=criterio_correcao, data_atualizacao=data_atualizacao,
            partes=[E.Parte(nome=p.nome, cpf_cnpj=p.cpf_cnpj,
                            parcelas=[E.Parcela(**q.model_dump()) for q in p.parcelas],
                            honorarios_contratuais_percentual=p.honorarios_contratuais_percentual,
                            honorarios_contratuais_cpf_cnpj=p.honorarios_contratuais_cpf_cnpj) for p in partes],
            numero_processo=numero_processo, autor=autor, reu=reu, percentual_acordo=percentual_acordo,
            selic_ec113=selic_ec113, selic_citacao=selic_citacao, permitir_deflacao=permitir_deflacao,
            juros_codigo=juros_codigo, juros_data_inicio=juros_data_inicio, rra=rra, gerar_sicar=gerar_sicar,
            honorarios=hon, operador=operador, instituicao=instituicao, cidade=cidade, uf=uf,
            observacoes=observacoes)
        try:
            r = await eng.calcular(calc)
            pdf = await E.baixar_pdf(r["identificador"])
        except E.ProjefErro as e:
            return [TextContent(type="text", text=f"Erro do Projef: {e}")]
        return _resultado(pdf, r["identificador"], r["url_pdf"], incluir_pdf, incluir_texto)

    @m.tool(annotations={"readOnlyHint": True, "openWorldHint": True})
    async def projef_recuperar(
        identificador: Annotated[str, Field(description="Identificador impresso no rodapé do PDF (ex.: 544240e0)")],
        incluir_pdf: bool = False,
        incluir_texto: bool = False,
    ):
        """Recupera um cálculo já feito no Projef Web pelo identificador (válido por 3 anos) e devolve
        os mesmos dados estruturados e o link do PDF. Não abre navegador."""
        try:
            pdf = await E.baixar_pdf(identificador)
        except E.ProjefErro as e:
            return [TextContent(type="text", text=f"Erro do Projef: {e}")]
        ident = "".join(ch for ch in identificador if ch.isalnum())
        return _resultado(pdf, ident, E.RELATORIO_URL.format(id=ident), incluir_pdf, incluir_texto)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="Servir em streamable-HTTP (modo remoto)")
    ap.add_argument("--host", default=os.environ.get("PROJEF_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PROJEF_PORT", "8092")))
    args = ap.parse_args()

    segredo = os.environ.get("PROJEF_PATH_SECRET", "").strip("/")
    path = f"/{segredo}/mcp" if segredo else "/mcp"
    hosts = [h.strip() for h in os.environ.get("PROJEF_ALLOWED_HOSTS", "").split(",") if h.strip()]
    seguranca = None
    if args.http:
        seguranca = TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(hosts),
            allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*"] if hosts else [],
            allowed_origins=[f"https://{h}" for h in hosts] + ["https://claude.ai"] if hosts else [],
        )

    m = FastMCP("projef", instructions=INSTRUCOES, host=args.host, port=args.port,
                streamable_http_path=path, stateless_http=True, transport_security=seguranca)
    eng = E.ProjefEngine(max_concorrencia=int(os.environ.get("PROJEF_CONCORRENCIA", "2")))
    registrar_ferramentas(m, eng)
    m.run(transport="streamable-http" if args.http else "stdio")


if __name__ == "__main__":
    main()
