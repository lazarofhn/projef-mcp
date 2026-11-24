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
import asyncio
import base64
import json
import os
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import BlobResourceContents, EmbeddedResource, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from projef_mcp import engine as E
from projef_mcp.opcoes import CRITERIOS_CORRECAO, HONORARIOS_MODOS, JUROS, ORIENTACAO, UFS
from projef_mcp.parser import parse_pdf

INSTRUCOES = f"""\
Servidor do Projef Web, a calculadora judicial da Justiça Federal do Rio Grande do Sul
(https://www.jfrs.jus.br/projefweb/). O cálculo é feito pelo servidor da JFRS; este MCP preenche o
formulário e devolve os números estruturados.

Cada resultado traz url_pdf, o link público do demonstrativo oficial em PDF (válido por 3 anos), e o
identificador do cálculo, que permite recuperá-lo depois com projef_recuperar. Os critérios de
correção e de juros dependem do título judicial; projef_opcoes lista os códigos aceitos.

{ORIENTACAO}"""

LIMITE_CARACTERES = 140_000      # resultado de ferramenta no claude.ai: ~150 mil caracteres
LIMITE_PDF_ANEXO = 90_000        # bytes; em base64 fica ~120 mil caracteres
TEMPO_MAX_CALCULO = 200          # segundos; o claude.ai encerra a chamada em 240 s

_IDS_CRITERIO = tuple(i for i, _ in CRITERIOS_CORRECAO)
_COD_JUROS = tuple(c for c, _ in JUROS)
CriterioId = Literal[_IDS_CRITERIO]          # type: ignore[valid-type]
JurosCodigo = Literal[_COD_JUROS]            # type: ignore[valid-type]
UF = Literal[tuple(UFS)]                     # type: ignore[valid-type]

DataMes = Annotated[str, Field(min_length=6, max_length=10,
                               description="Mês/ano no formato mm/aaaa (também aceita aaaa-mm e dd/mm/aaaa)")]
Valor = Annotated[float | str, Field(description="Valor em reais: número (1500.25) ou texto ('1.500,25')")]
Percentual = Annotated[float, Field(ge=0, le=100)]


class ParcelaIn(BaseModel):
    data: Annotated[DataMes, Field(description="Mês/ano da parcela: data do recolhimento (indébito) "
                                               "ou do vencimento, mm/aaaa")]
    principal: Annotated[Valor, Field(description="Valor nominal da parcela")]
    juros: Annotated[Valor | None, Field(description="Juros já apurados na parcela, se houver (raro)")] = None
    selic: Annotated[Valor | None, Field(description="Selic já apurada na parcela, se houver (raro)")] = None


class ParteIn(BaseModel):
    nome: Annotated[str, Field(min_length=1, max_length=200, description="Nome do credor")]
    cpf_cnpj: Annotated[str, Field(min_length=11, max_length=18,
                                   description="CPF ou CNPJ do credor, com ou sem pontuação; os dígitos "
                                               "verificadores são conferidos")]
    parcelas: Annotated[list[ParcelaIn], Field(min_length=1, max_length=1200)]
    honorarios_contratuais_percentual: Annotated[Percentual | None, Field(
        description="Destaque de honorários contratuais em %, opcional")] = None
    honorarios_contratuais_cpf_cnpj: Annotated[str | None, Field(
        description="CPF/CNPJ do beneficiário dos honorários contratuais")] = None


class HonorariosIn(BaseModel):
    modo: Annotated[Literal["0", "1", "2", "3", "4", "5"], Field(
        description="0 nenhum; 3 valor da condenação; 1 valor da causa/proveito econômico; 2 valor certo; "
                    "4 condenação sem descontos; 5 condenação com descontos até considerar_ate")] = "3"
    escalonar_fazenda: Annotated[bool, Field(
        description="Escalonar pelas faixas do art. 85, §3º, do CPC (Fazenda Pública é parte); exige faixas")] = False
    faixas: Annotated[list[Percentual] | None, Field(
        min_length=5, max_length=5,
        description="Os 5 percentuais das faixas do art. 85, §3º (I a V), ex. [10, 8, 5, 3, 1]")] = None
    percentual: Annotated[Percentual | None, Field(description="Percentual único, quando não escalona")] = None
    cpf_cnpj: Annotated[str | None, Field(description="CPF/CNPJ do advogado ou da sociedade beneficiária")] = None
    considerar_ate: Annotated[DataMes | None, Field(description="Parcelas consideradas até este mês (modo 5)")] = None
    valor: Annotated[Valor | None, Field(description="Valor da causa/proveito econômico ou valor certo (modos 1 e 2)")] = None
    data: Annotated[DataMes | None, Field(description="Mês/ano do valor informado (modos 1 e 2)")] = None
    data_inicio_juros: Annotated[DataMes | None, Field(description="Início dos juros sobre os honorários")] = None
    minimo: Annotated[float | None, Field(ge=0, description="Limite mínimo em R$")] = None
    maximo: Annotated[float | None, Field(ge=0, description="Limite máximo em R$")] = None
    correcao_manual_cap4: Annotated[bool | None, Field(
        description="Corrigir os honorários pelo critério do Cap. 4 do Manual (Ações Condenatórias em Geral)")] = None


def _resultado(pdf: bytes, ident: str, url: str, incluir_pdf: bool, incluir_texto: bool) -> list:
    dados = parse_pdf(pdf)
    texto = dados.pop("_texto_integral")
    if incluir_texto:
        dados["texto_integral"] = texto
    payload = {"identificador": ident, "url_pdf": url, **dados}

    corpo = json.dumps(payload, ensure_ascii=False, indent=1)
    if len(corpo) > LIMITE_CARACTERES:
        payload.pop("texto_integral", None)
        avisos = []
        for dem in payload.get("demonstrativo_parcelas", []):
            n = len(dem["parcelas"])
            if n > 60:
                dem["parcelas"] = dem["parcelas"][:60]
                avisos.append(f"{dem['parte']}: mostradas 60 de {n} parcelas")
        payload["aviso_truncamento"] = ("Resultado reduzido para caber no limite de resposta. "
                                        + "; ".join(avisos) + ". O demonstrativo completo está em url_pdf.")
        corpo = json.dumps(payload, ensure_ascii=False, indent=1)

    content: list = [TextContent(type="text", text=corpo)]
    if incluir_pdf:
        if len(pdf) <= LIMITE_PDF_ANEXO:
            content.append(EmbeddedResource(type="resource", resource=BlobResourceContents(
                uri=url, mimeType="application/pdf", blob=base64.b64encode(pdf).decode())))
        else:
            content.append(TextContent(type="text", text=(
                f"PDF não anexado: {len(pdf) // 1024} KB passa do limite de anexo "
                f"({LIMITE_PDF_ANEXO // 1024} KB). Use o link url_pdf.")))
    return content


def _erro_inesperado(e: Exception) -> ToolError:
    return ToolError(f"Falha ao operar o Projef Web ({type(e).__name__}: {str(e)[:300]}). "
                     "O site da JFRS pode estar fora do ar ou ter mudado de layout; tente de novo em alguns "
                     "minutos ou confira em https://www.jfrs.jus.br/projefweb/.")


def registrar_ferramentas(m: FastMCP, eng: E.ProjefEngine) -> None:

    @m.tool(title="Opções do Projef", annotations=ToolAnnotations(
        title="Opções do Projef", readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        openWorldHint=False))
    def projef_opcoes() -> dict:
        """Lista os códigos aceitos por projef_calcular: critérios de correção monetária (id), taxas de
        juros moratórios (codigo), modos de honorários (codigo) e UFs, com a orientação de uso para
        repetição de indébito tributário e ações condenatórias em geral. Não acessa a internet."""
        return {
            "criterios_correcao": [{"id": i, "descricao": d} for i, d in CRITERIOS_CORRECAO],
            "juros_moratorios": [{"codigo": c, "descricao": d} for c, d in JUROS],
            "honorarios_modos": [{"codigo": c, "descricao": d} for c, d in HONORARIOS_MODOS],
            "ufs": UFS,
            "orientacao": ORIENTACAO,
        }

    @m.tool(title="Calcular no Projef", annotations=ToolAnnotations(
        title="Calcular no Projef", readOnlyHint=False, destructiveHint=False, idempotentHint=False,
        openWorldHint=True))
    async def projef_calcular(
        criterio_correcao: Annotated[CriterioId, Field(
            description="id do critério de correção monetária (lista em projef_opcoes). 3 = repetição de "
                        "indébito tributário (Manual da JF, Selic); 65 = ações condenatórias em geral (Manual 2022)")],
        data_atualizacao: Annotated[DataMes, Field(description="Data-base da atualização (mm/aaaa)")],
        partes: Annotated[list[ParteIn], Field(min_length=1, max_length=50,
                                               description="Credores, cada um com suas parcelas")],
        selic_ec113: Annotated[bool, Field(description="Aplicar Selic a partir de 12/2021 (EC 113/21)")] = False,
        selic_citacao: Annotated[bool, Field(description="Aplicar Selic a partir da citação")] = False,
        permitir_deflacao: Annotated[bool, Field(description="Permitir deflação do valor nominal da parcela")] = False,
        juros_codigo: Annotated[JurosCodigo, Field(
            description="Código da taxa de juros moratórios (lista em projef_opcoes); '0' = sem juros")] = "0",
        juros_data_inicio: Annotated[DataMes | None, Field(
            description="Início dos juros (ex.: mês da citação); necessário quando há juros")] = None,
        honorarios: Annotated[HonorariosIn | None, Field(description="Honorários de sucumbência")] = None,
        numero_processo: Annotated[str | None, Field(
            description="Número CNJ do processo (20 dígitos, com ou sem pontuação), opcional")] = None,
        autor: Annotated[str | None, Field(max_length=200)] = None,
        reu: Annotated[str | None, Field(max_length=200)] = None,
        percentual_acordo: Annotated[float | None, Field(ge=30, le=100, description="Percentual de acordo")] = None,
        rra: Annotated[bool, Field(
            description="As parcelas são Rendimentos Recebidos Acumuladamente (art. 12-A da Lei 7.713/88)")] = False,
        gerar_sicar: Annotated[bool, Field(
            description="Gerar o demonstrativo SICAR-JF4R; consulta o número do processo no eproc da 4ª Região, "
                        "que substitui autor e réu pelos dados reais do processo")] = False,
        operador: Annotated[str | None, Field(max_length=200, description="Confeccionador do cálculo")] = None,
        instituicao: Annotated[str | None, Field(max_length=200)] = None,
        cidade: Annotated[str | None, Field(max_length=100)] = None,
        uf: UF | None = None,
        observacoes: Annotated[str | None, Field(max_length=2000)] = None,
        incluir_pdf: Annotated[bool, Field(
            description="Anexar também o PDF (até 90 KB); o link url_pdf vem sempre")] = False,
        incluir_texto: Annotated[bool, Field(description="Incluir o texto integral do demonstrativo")] = False,
    ):
        """Faz um novo cálculo judicial no Projef Web da JFRS: corrige as parcelas informadas, aplica
        juros/Selic e honorários, e devolve o identificador, o link público do PDF oficial (url_pdf), o
        resumo por parte, as sucumbências, o total da conta, os critérios aplicados e o demonstrativo
        parcela a parcela (principal, coeficiente, principal corrigido, juros, Selic % e R$, total).
        Cria um registro novo nos servidores da JFRS a cada chamada (guardado por 3 anos) e leva de 15
        a 40 segundos. Para reabrir um cálculo já feito, use projef_recuperar."""
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
            r = await asyncio.wait_for(eng.calcular(calc), TEMPO_MAX_CALCULO)
            pdf = await E.baixar_pdf(r["identificador"])
        except E.ProjefErro as e:
            raise ToolError(f"O Projef recusou o cálculo: {e}") from e
        except asyncio.TimeoutError as e:
            raise ToolError(f"O Projef não respondeu em {TEMPO_MAX_CALCULO} s (fila cheia ou site lento). "
                            "Tente de novo em instantes.") from e
        except Exception as e:  # noqa: BLE001
            raise _erro_inesperado(e) from e
        return _resultado(pdf, r["identificador"], r["url_pdf"], incluir_pdf, incluir_texto)

    @m.tool(title="Recuperar cálculo do Projef", annotations=ToolAnnotations(
        title="Recuperar cálculo do Projef", readOnlyHint=True, destructiveHint=False, idempotentHint=True,
        openWorldHint=True))
    async def projef_recuperar(
        identificador: Annotated[str, Field(
            pattern=r"^[0-9a-zA-Z]{4,16}$",
            description="Identificador do cálculo, impresso no rodapé do PDF do Projef (ex.: 544240e0)")],
        incluir_pdf: Annotated[bool, Field(description="Anexar também o PDF (até 90 KB)")] = False,
        incluir_texto: Annotated[bool, Field(description="Incluir o texto integral do demonstrativo")] = False,
    ):
        """Lê um cálculo já feito no Projef Web a partir do identificador (válido por 3 anos) e devolve
        os mesmos dados estruturados e o link do PDF de projef_calcular. Não cria cálculo novo nem abre
        navegador. Para fazer um cálculo novo, use projef_calcular."""
        try:
            pdf = await E.baixar_pdf(identificador)
        except E.ProjefErro as e:
            raise ToolError(f"{e} Confira o identificador no rodapé do PDF.") from e
        except Exception as e:  # noqa: BLE001
            raise _erro_inesperado(e) from e
        return _resultado(pdf, identificador, E.RELATORIO_URL.format(id=identificador), incluir_pdf, incluir_texto)


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
