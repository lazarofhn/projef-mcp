"""Automação headless do Projef Web (JFRS) com Playwright.

O Projef Web é um app GWT/Ext JS: o navegador só coleta os dados; o cálculo é
feito no servidor da JFRS quando o cálculo é gravado (gravaCalculo) e o PDF é
servido em /projefweb/app/relatorio?id=<identificador>.

Este módulo preenche o formulário num Chromium invisível, clica em "Calcular",
lê o identificador devolvido e baixa o PDF por HTTP.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from playwright.async_api import Browser, Page, async_playwright

BASE_URL = "https://www.jfrs.jus.br/projefweb/"
RELATORIO_URL = BASE_URL + "app/relatorio?id={id}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


HTTP_UA = "projef-mcp (+https://github.com/lazarofhn/projef-mcp)"


class ProjefErro(Exception):
    """Erro de validação ou de execução devolvido pelo Projef."""


async def _instalar_chromium() -> None:
    """Baixa o Chromium do Playwright (só na primeira execução)."""
    import sys
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise ProjefErro("Não foi possível instalar o Chromium do Playwright. Rode manualmente: "
                         f"python -m playwright install chromium ({err.decode(errors='ignore')[-300:]})")


# --------------------------------------------------------------------------- #
# Modelo de entrada
# --------------------------------------------------------------------------- #
@dataclass
class Parcela:
    data: str                      # mm/aaaa
    principal: Any                 # número ou string "1.234,56"
    juros: Any = None
    selic: Any = None


@dataclass
class Parte:
    nome: str
    cpf_cnpj: str
    parcelas: list[Parcela]
    honorarios_contratuais_percentual: Any = None
    honorarios_contratuais_cpf_cnpj: str | None = None


@dataclass
class Honorarios:
    modo: str = "0"                # código do combo "honorarios"
    percentual: Any = None
    cpf_cnpj: str | None = None
    considerar_ate: str | None = None      # mm/aaaa (data_limite_descontos)
    valor: Any = None                      # valor certo / valor da causa
    data: str | None = None                # mm/aaaa do valor
    data_inicio_juros: str | None = None   # mm/aaaa
    minimo: Any = None
    maximo: Any = None
    escalonar_fazenda: bool = False        # art. 85, §3º, CPC
    faixas: list[Any] | None = None        # percentuais das 5 faixas do §3º
    correcao_manual_cap4: bool | None = None


@dataclass
class Calculo:
    criterio_correcao: int
    data_atualizacao: str                  # mm/aaaa
    partes: list[Parte]
    numero_processo: str | None = None
    autor: str | None = None
    reu: str | None = None
    percentual_acordo: Any = None
    selic_ec113: bool = False
    selic_citacao: bool = False
    permitir_deflacao: bool = False
    juros_codigo: str = "0"
    juros_data_inicio: str | None = None
    rra: bool = False
    gerar_sicar: bool = False
    honorarios: Honorarios | None = None
    operador: str | None = None
    instituicao: str | None = None
    cidade: str | None = None
    uf: str | None = None
    observacoes: str | None = None


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def br_num(v: Any) -> str:
    """Converte número/str para o formato aceito pelo Projef: 1234,56."""
    if v is None or v == "":
        return "0"
    if isinstance(v, (int, float, Decimal)):
        d = Decimal(str(v))
    else:
        s = str(v).strip().replace("R$", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            d = Decimal(s)
        except InvalidOperation as e:
            raise ProjefErro(f"Valor numérico inválido: {v!r}") from e
    q = d.quantize(Decimal("0.01"))
    return f"{q:.2f}".replace(".", ",")


_MMAAAA = re.compile(r"^(0[1-9]|1[0-2])/\d{4}$")


def mmaaaa(v: str, campo: str) -> str:
    s = str(v).strip()
    m = re.match(r"^(\d{1,2})[/-](\d{4})$", s)
    if m:
        s = f"{int(m.group(1)):02d}/{m.group(2)}"
    m = re.match(r"^(\d{4})-(\d{1,2})(?:-\d{1,2})?$", s)  # ISO aaaa-mm[-dd]
    if m:
        s = f"{int(m.group(2)):02d}/{m.group(1)}"
    m = re.match(r"^\d{1,2}/(\d{1,2})/(\d{4})$", s)       # dd/mm/aaaa
    if m:
        s = f"{int(m.group(1)):02d}/{m.group(2)}"
    if not _MMAAAA.match(s):
        raise ProjefErro(f"{campo}: data deve estar no formato mm/aaaa (recebido {v!r})")
    return s


def so_digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def cpf_cnpj_valido(v: str) -> bool:
    d = so_digitos(v)
    if len(d) == 11:
        if d == d[0] * 11:
            return False
        for n in (9, 10):
            s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
            if (s * 10 % 11) % 10 != int(d[n]):
                return False
        return True
    if len(d) == 14:
        if d == d[0] * 14:
            return False
        for n in (12, 13):
            pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
            s = sum(int(d[i]) * pesos[i] for i in range(n))
            dv = 0 if s % 11 < 2 else 11 - s % 11
            if dv != int(d[n]):
                return False
        return True
    return False


def numero_cnj_valido(n: str) -> bool:
    d = so_digitos(n)
    if len(d) != 20:
        return False
    seq, dv, resto = d[:7], d[7:9], d[9:]
    return 98 - int(seq + resto + "00") % 97 == int(dv)


# --------------------------------------------------------------------------- #
# JS auxiliar injetado na página (usa a API do Ext JS 3)
# --------------------------------------------------------------------------- #
JS_HELPERS = r"""
() => {
  if (window.__pj) return true;
  window.__pj = {
    comp(name, inWindow) {
      let found = null;
      Ext.ComponentMgr.all.each(c => {
        if (found) return false;
        if (c.hiddenName === name || c.name === name) {
          const inWin = !!(c.el && c.el.dom && c.el.dom.closest('.x-window'));
          if (inWindow === undefined || inWin === inWindow) found = c;
        }
      });
      return found;
    },
    setCombo(name, value, inWindow) {
      const c = this.comp(name, inWindow);
      if (!c) throw new Error('Campo não encontrado: ' + name);
      const i = c.store.findBy(r => String(r.get(c.valueField)) === String(value));
      if (i < 0) throw new Error('Opção inválida para ' + name + ': ' + value);
      const r = c.store.getAt(i);
      c.setValue(r.get(c.valueField));
      c.fireEvent('select', c, r, i);
      return c.getRawValue();
    },
    setCheck(name, value) {
      const c = this.comp(name);
      if (!c) throw new Error('Checkbox não encontrado: ' + name);
      if (c.getValue() !== !!value) c.setValue(!!value);
      return c.getValue();
    },
    dialog() {
      const ws = [...document.querySelectorAll('.x-window-dlg')].filter(w => w.offsetParent !== null && w.style.visibility !== 'hidden');
      if (!ws.length) return null;
      const w = ws[ws.length - 1];
      const t = w.querySelector('.x-window-header-text');
      const b = w.querySelector('.ext-mb-text');
      return {titulo: t ? t.innerText.trim() : '', texto: b ? b.innerText.trim() : w.innerText.trim()};
    },
    closeDialog() {
      try { Ext.MessageBox.hide(); } catch (e) {}
    }
  };
  return true;
}
"""


# --------------------------------------------------------------------------- #
# Motor
# --------------------------------------------------------------------------- #
class ProjefEngine:
    def __init__(self, max_concorrencia: int = 2, headless: bool = True):
        self._pw = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concorrencia)
        self._headless = headless

    async def _get_browser(self) -> Browser:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                if self._pw is None:
                    self._pw = await async_playwright().start()
                try:
                    self._browser = await self._pw.chromium.launch(headless=self._headless)
                except Exception as e:  # Chromium do Playwright ainda não baixado
                    if "Executable doesn't exist" not in str(e):
                        raise
                    await _instalar_chromium()
                    self._browser = await self._pw.chromium.launch(headless=self._headless)
            return self._browser

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._pw = None

    # ---- helpers de página ------------------------------------------------- #
    @staticmethod
    async def _tab(pg: Page, texto: str) -> None:
        await pg.locator(".x-tab-strip-text").filter(has_text=texto).first.click()
        await pg.wait_for_timeout(250)

    @staticmethod
    async def _fill(pg: Page, name: str, valor: str, scope: str = "body") -> None:
        loc = pg.locator(f"{scope} input[name='{name}']:visible, {scope} textarea[name='{name}']:visible").first
        await loc.click()
        await loc.fill(valor)
        await loc.press("Tab")

    @staticmethod
    async def _dialog(pg: Page) -> dict | None:
        return await pg.evaluate("() => window.__pj.dialog()")

    async def _check_erro(self, pg: Page, etapa: str) -> None:
        d = await self._dialog(pg)
        if d:
            await pg.evaluate("() => window.__pj.closeDialog()")
            raise ProjefErro(f"{etapa}: {d['titulo']} — {d['texto']}")

    # ---- fluxo principal --------------------------------------------------- #
    async def calcular(self, c: Calculo) -> dict:
        self._validar(c)
        async with self._sem:
            browser = await self._get_browser()
            ctx = await browser.new_context(viewport={"width": 1400, "height": 1000}, user_agent=UA,
                                            locale="pt-BR")
            pg = await ctx.new_page()
            try:
                return await self._executar(pg, c)
            finally:
                await ctx.close()

    def _validar(self, c: Calculo) -> None:
        if not c.partes:
            raise ProjefErro("Informe ao menos uma parte com parcelas.")
        for p in c.partes:
            if not p.parcelas:
                raise ProjefErro(f"A parte {p.nome!r} está sem parcelas.")
            if not cpf_cnpj_valido(p.cpf_cnpj):
                raise ProjefErro(f"CPF/CNPJ inválido para a parte {p.nome!r}: {p.cpf_cnpj}")
            if p.honorarios_contratuais_cpf_cnpj and not cpf_cnpj_valido(p.honorarios_contratuais_cpf_cnpj):
                raise ProjefErro(f"CPF/CNPJ dos honorários contratuais inválido: {p.honorarios_contratuais_cpf_cnpj}")
        if c.honorarios and c.honorarios.cpf_cnpj and not cpf_cnpj_valido(c.honorarios.cpf_cnpj):
            raise ProjefErro(f"CPF/CNPJ dos honorários sucumbenciais inválido: {c.honorarios.cpf_cnpj}")
        if c.numero_processo and not numero_cnj_valido(c.numero_processo):
            raise ProjefErro("Número do processo inválido (padrão CNJ, 20 dígitos com DV conferido).")

    async def _executar(self, pg: Page, c: Calculo) -> dict:
        await pg.goto(BASE_URL, wait_until="networkidle", timeout=60000)
        await pg.wait_for_function("() => window.Ext && Ext.ComponentMgr && Ext.ComponentMgr.all.getCount() > 50",
                                   timeout=60000)
        await pg.wait_for_timeout(500)
        await pg.evaluate(JS_HELPERS)

        # 1. Dados do processo
        await self._tab(pg, "Dados Processo")
        await pg.evaluate("v => window.__pj.setCheck('eproc', v)", bool(c.gerar_sicar))
        if c.numero_processo:
            await self._fill(pg, "numero_processo", so_digitos(c.numero_processo))
            await pg.wait_for_timeout(1500)       # consulta automática ao eproc, se SICAR ligado
            await self._check_erro(pg, "Dados do processo")
        if c.autor:
            await self._fill(pg, "autor_processo", c.autor)
        if c.reu:
            await self._fill(pg, "reu_processo", c.reu)
        if c.percentual_acordo not in (None, ""):
            await self._fill(pg, "percentual_acordo", br_num(c.percentual_acordo))

        # 2. Correção monetária
        await self._tab(pg, "Correção Monetária")
        await pg.evaluate("v => window.__pj.setCombo('correcao_monetaria', v)", int(c.criterio_correcao))
        await pg.evaluate("v => window.__pj.setCheck('selic_ec113', v)", bool(c.selic_ec113))
        await pg.evaluate("v => window.__pj.setCheck('selic_citacao', v)", bool(c.selic_citacao))
        await pg.evaluate("v => window.__pj.setCheck('permitir_deflacao', v)", bool(c.permitir_deflacao))
        await self._fill(pg, "data_atualizacao", mmaaaa(c.data_atualizacao, "data_atualizacao"))
        await self._check_erro(pg, "Correção monetária")

        # 3. Juros moratórios
        await self._tab(pg, "Juros Moratórios")
        await pg.evaluate("v => window.__pj.setCombo('juros_moratorios', v)", str(c.juros_codigo or "0"))
        if c.juros_data_inicio:
            await self._fill(pg, "data_inicio_juros", mmaaaa(c.juros_data_inicio, "juros_data_inicio"))
        await self._check_erro(pg, "Juros moratórios")

        # 4. Partes e parcelas
        await self._tab(pg, "Partes e Parcelas")
        await pg.evaluate("v => window.__pj.setCheck('rra', v)", bool(c.rra))
        for parte in c.partes:
            await self._inserir_parte(pg, parte)

        # 5. Honorários
        if c.honorarios:
            await self._tab(pg, "Honorários Advocatícios")
            await self._honorarios(pg, c.honorarios)

        # 6. Dados finais
        await self._tab(pg, "Dados Finais")
        for nome, val in (("operador", c.operador), ("instituicao", c.instituicao),
                          ("cidade", c.cidade), ("observacoes", c.observacoes)):
            if val:
                await self._fill(pg, nome, val)
        if c.uf:
            await pg.evaluate("v => window.__pj.setCombo('uf', v)", c.uf.upper())

        # 7. Calcular
        await pg.get_by_role("button", name="Calcular").click()
        ident = None
        for _ in range(120):                       # até ~60 s
            await pg.wait_for_timeout(500)
            d = await self._dialog(pg)
            if not d:
                continue
            m = re.search(r"identificador:\s*([0-9a-zA-Z]+)", d["texto"])
            if m:
                ident = m.group(1)
                break
            if "aguarde" in (d["titulo"] + d["texto"]).lower():
                continue
            raise ProjefErro(f"{d['titulo']} — {d['texto']}")
        if not ident:
            raise ProjefErro("O Projef não devolveu o identificador do cálculo (tempo esgotado).")
        return {"identificador": ident, "url_pdf": RELATORIO_URL.format(id=ident)}

    async def _inserir_parte(self, pg: Page, p: Parte) -> None:
        await pg.get_by_text("Inserir", exact=True).first.click()
        win = pg.locator(".x-window:visible").last
        await win.locator("input[name='nome']").wait_for(state="visible", timeout=15000)
        await self._fill(pg, "nome", p.nome, ".x-window")
        await self._fill(pg, "cpf_cnpj", so_digitos(p.cpf_cnpj), ".x-window")
        if p.honorarios_contratuais_percentual not in (None, "", 0):
            await self._fill(pg, "percentual_honorarios_contratuais", br_num(p.honorarios_contratuais_percentual),
                             ".x-window")
            if p.honorarios_contratuais_cpf_cnpj:
                await self._fill(pg, "cpf_cnpj_honorarios_contratuais",
                                 so_digitos(p.honorarios_contratuais_cpf_cnpj), ".x-window")

        linhas = []
        for i, q in enumerate(p.parcelas, 1):
            linha = f"{mmaaaa(q.data, f'parcela {i}')}\t{br_num(q.principal)}"
            if q.juros not in (None, "") or q.selic not in (None, ""):
                linha += f"\t{br_num(q.juros)}\t{br_num(q.selic)}"
            linhas.append(linha)

        await win.locator(".x-tab-strip-text", has_text="Colar de Planilha").click()
        ta = win.locator("textarea:visible").first
        await ta.fill("\n".join(linhas))
        await win.get_by_role("button", name="Criar Parcela(s)").click()
        await pg.wait_for_timeout(600)
        await self._check_erro(pg, f"Parcelas de {p.nome}")

        n = await win.locator(".x-grid3-row").count()
        if n < len(p.parcelas):
            raise ProjefErro(f"Parcelas de {p.nome}: o Projef aceitou {n} de {len(p.parcelas)} parcelas.")

        await win.get_by_role("button", name="Gravar e Voltar").click()
        await pg.wait_for_timeout(600)
        await self._check_erro(pg, f"Parte {p.nome}")
        if await pg.locator(".x-window:visible input[name='nome']").count():
            raise ProjefErro(f"Parte {p.nome}: o Projef não aceitou os dados (verifique nome e CPF/CNPJ).")

    async def _honorarios(self, pg: Page, h: Honorarios) -> None:
        await pg.evaluate("v => window.__pj.setCheck('fazenda_publica_parte', v)", bool(h.escalonar_fazenda))
        await pg.evaluate("v => window.__pj.setCombo('honorarios', v)", str(h.modo))
        await pg.wait_for_timeout(300)
        if h.correcao_manual_cap4 is not None:
            await pg.evaluate("v => window.__pj.setCheck('correcao_monetaria_honorarios', v)",
                              bool(h.correcao_manual_cap4))
        campos = [
            ("cpf_cnpj_honorarios", so_digitos(h.cpf_cnpj) if h.cpf_cnpj else None),
            ("data_limite_descontos", mmaaaa(h.considerar_ate, "considerar_ate") if h.considerar_ate else None),
            ("data_honorarios", mmaaaa(h.data, "honorarios.data") if h.data else None),
            ("valor_honorarios", br_num(h.valor) if h.valor not in (None, "") else None),
            ("data_inicio_juros_honorarios",
             mmaaaa(h.data_inicio_juros, "honorarios.data_inicio_juros") if h.data_inicio_juros else None),
            ("honorarios_minimo", br_num(h.minimo) if h.minimo not in (None, "") else None),
            ("honorarios_maximo", br_num(h.maximo) if h.maximo not in (None, "") else None),
        ]
        if h.escalonar_fazenda:
            for i, f in enumerate((h.faixas or [])[:5], 1):
                campos.append((f"percentual_honorarios{i}", br_num(f)))
        elif h.percentual not in (None, ""):
            campos.append(("percentual_honorarios", br_num(h.percentual)))
        for nome, val in campos:
            if val is None:
                continue
            visivel = await pg.locator(f"input[name='{nome}']:visible").count()
            if not visivel:
                raise ProjefErro(f"Honorários: o campo {nome} não se aplica ao modo {h.modo}.")
            await self._fill(pg, nome, val)
        await self._check_erro(pg, "Honorários")


# --------------------------------------------------------------------------- #
# Download do PDF (HTTP puro)
# --------------------------------------------------------------------------- #
async def baixar_pdf(identificador: str) -> bytes:
    ident = re.sub(r"[^0-9a-zA-Z]", "", identificador)
    if not ident:
        raise ProjefErro("Identificador vazio.")
    async with httpx.AsyncClient(timeout=120, headers={"User-Agent": HTTP_UA}, follow_redirects=True) as cli:
        r = await cli.get(RELATORIO_URL.format(id=ident))
    if "pdf" not in r.headers.get("content-type", ""):
        raise ProjefErro("O Projef não gerou o demonstrativo para esse identificador "
                         "(identificador inexistente/expirado ou dados inválidos).")
    return r.content
