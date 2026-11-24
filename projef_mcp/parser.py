"""Converte o PDF do Projef Web em dados estruturados."""
from __future__ import annotations

import io
import re
import unicodedata

import pypdf

NUM = r"-?[\d.]+,\d+%?"
_num_re = re.compile(rf"^{NUM}$")


def num(s: str):
    """'1.234,56' -> 1234.56 ; '63,87%' -> 63.87 ; '-' -> None."""
    s = s.strip()
    if s in ("-", ""):
        return None
    s = s.rstrip("%").replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _slug(s: str) -> str:
    s = s.replace("%", " pct").replace("$", " valor").replace("(R valor)", "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.lower()).strip("_")
    return s


_RODAPE = re.compile(r"^(Gere novamente este cálculo|Projef Web - Programa|\d+$|\s*$)")


def _linhas(texto: str) -> list[str]:
    return [l.rstrip() for l in texto.splitlines() if not _RODAPE.match(l.strip())]


def _cabecalho_colunas(header: str) -> list[str]:
    """'# Data Principal (A) Coef. ... (B) ... Total (R$) (H = C + E + G) Obs.' -> slugs."""
    corpo = re.sub(r"^#\s*Data\s*", "", header)
    corpo = corpo.replace("(R$)", "")
    partes = re.split(r"\([A-Z](?:\s*=\s*(?:[^()]|\([^()]*\))*)?\)", corpo)
    cols = [_slug(p) for p in partes if _slug(p) and _slug(p) != "obs"]
    return cols


def _tokens_numericos(resto: str) -> tuple[list[str], str]:
    toks = resto.split()
    vals = []
    i = 0
    while i < len(toks) and (_num_re.match(toks[i]) or toks[i] == "-"):
        vals.append(toks[i])
        i += 1
    return vals, " ".join(toks[i:])


def _linha_nome_valores(l: str, n: int):
    """'NOME COM ESPAÇOS 1,00 2,00 3,00' -> ('NOME COM ESPAÇOS', [1.0, 2.0, 3.0]) se terminar em n números."""
    toks = l.split()
    if len(toks) <= n:
        return None
    cauda = toks[-n:]
    if not all(_num_re.match(t) or t == "-" for t in cauda):
        return None
    return " ".join(toks[:-n]), [num(t) for t in cauda]


def parse_pdf(pdf: bytes) -> dict:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    paginas = [p.extract_text() or "" for p in reader.pages]
    texto = "\n".join(paginas)
    L = _linhas(texto)
    out: dict = {"paginas": len(paginas)}

    m = re.search(r"identificador\s+([0-9a-zA-Z]+)", texto)
    out["identificador"] = m.group(1) if m else None
    for rot, chave in (("Processo:", "processo"), ("Autor:", "autor"), ("Réu:", "reu"),
                       ("Cálculo elaborado por:", "elaborado_por")):
        m = re.search(rf"^{re.escape(rot)}[ \t]*(\S.*)$", texto, re.M)
        if m:
            out[chave] = m.group(1).strip()
    m = re.search(r"Motor:\s*([\d.]+)", texto)
    v = re.search(r"Versão:\s*([\d.]+)", texto)
    out["versao"] = {"programa": v.group(1) if v else None, "motor": m.group(1) if m else None}

    # ---- Resumo: partes ------------------------------------------------------
    partes = []
    total_partes = None
    try:
        i = next(k for k, l in enumerate(L) if l.startswith("Nome Principal corrigido"))
        for l in L[i + 1:]:
            if l.startswith("Total Partes"):
                t = _linha_nome_valores(l, 4)
                if t:
                    total_partes = dict(zip(("principal_corrigido", "juros", "selic", "total"), t[1]))
                break
            t = _linha_nome_valores(l, 4)
            if t:
                partes.append({"nome": t[0], **dict(zip(("principal_corrigido", "juros", "selic", "total"), t[1]))})
    except StopIteration:
        pass
    out["resumo_partes"] = partes
    out["total_partes"] = total_partes

    # ---- Resumo: sucumbências ------------------------------------------------
    sucs = []
    total_suc = None
    try:
        i = next(k for k, l in enumerate(L) if l.startswith("Descrição Principal corrigido Juros/Selic Total"))
        for l in L[i + 1:]:
            if l.startswith("Total de Sucumbências"):
                total_suc = num(l.split()[-1])
                break
            t = _linha_nome_valores(l, 3)
            if t:
                sucs.append({"descricao": t[0], **dict(zip(("principal_corrigido", "juros_selic", "total"), t[1]))})
    except StopIteration:
        pass
    out["resumo_sucumbencias"] = sucs
    out["total_sucumbencias"] = total_suc

    # ---- Totalização ---------------------------------------------------------
    tot = []
    for l in L:
        if re.match(r"^(SUBTOTAL|TOTAL DA CONTA|TOTAL|DEDUÇ|\(-\)|\(\+\))", l) and _num_re.match(l.split()[-1]):
            tot.append({"descricao": " ".join(l.split()[:-1]), "valor": num(l.split()[-1])})
    out["totalizacao"] = tot
    m = re.search(r"TOTAL DA CONTA EM (\d{2}/\d{4})\s+(" + NUM + ")", texto)
    if m:
        out["total_da_conta"] = {"data_base": m.group(1), "valor": num(m.group(2))}

    # ---- Critérios -----------------------------------------------------------
    m = re.search(r"Critérios e parâmetros do cálculo\s*(.+?)\nVersão:", texto, re.S)
    if m:
        out["criterios"] = re.sub(r"[ \t]+", " ", m.group(1)).strip()

    # ---- Demonstrativo de parcelas (por parte) -------------------------------
    demonstrativos = []
    atual = None
    cols: list[str] = []
    for l in L:
        if l.startswith("Cálculo para:"):
            atual = {"parte": l.split(":", 1)[1].strip(), "parcelas": [], "total": None}
            demonstrativos.append(atual)
            continue
        if atual is None:
            continue
        if l.startswith("# Data"):
            cols = _cabecalho_colunas(l)
            continue
        m = re.match(r"^(\d+)\s+(\d{2}/\d{2,4})\s+(.*)$", l)
        if m and cols:
            vals, obs = _tokens_numericos(m.group(3))
            row = {"n": int(m.group(1)), "data": m.group(2)}
            row.update({c: num(v) for c, v in zip(cols, vals)})
            if obs:
                row["obs"] = obs
            atual["parcelas"].append(row)
            continue
        if l.startswith("Totais") and cols:
            vals, _ = _tokens_numericos(l[len("Totais"):])
            atual["totais_brutos"] = [num(v) for v in vals]
            continue
        m = re.match(r"^Total para:\s*(.+?)\s+(" + NUM + r")$", l)
        if m:
            atual["total"] = num(m.group(2))
            atual = None
    out["demonstrativo_parcelas"] = demonstrativos

    # ---- SICAR ---------------------------------------------------------------
    if "SICAR" in texto and "Data-Base:" in texto:
        sicar = {}
        i = texto.find("Sistema de Integração de Cálculos")
        for l in _linhas(texto[i:]):
            if ":" in l and not l.startswith("Sistema"):
                k, v = l.split(":", 1)
                sicar[_slug(k)] = v.strip()
        out["sicar"] = sicar

    # ---- Seções que ficam como texto (sucumbências/honorários detalhados) ----
    for titulo, chave in (("DEMONSTRATIVO DE SUCUMBÊNCIAS", "demonstrativo_sucumbencias_texto"),
                          ("DEMONSTRATIVO DE HONORÁRIOS ADVOCATÍCIOS", "demonstrativo_honorarios_texto"),
                          ("DEMONSTRATIVO PARA FINS DE RENDIMENTOS RECEBIDOS", "rra_texto")):
        for p in paginas:
            if titulo in p:
                out.setdefault(chave, "")
                out[chave] += "\n".join(_linhas(p[p.find(titulo):])) + "\n"

    out["_texto_integral"] = "\n".join(L)
    return out
