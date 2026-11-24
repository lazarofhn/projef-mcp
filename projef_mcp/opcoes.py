"""Opções dos combos do Projef Web (versão 3.42.11, lidas do próprio app em 19/11/2026)."""

CRITERIOS_CORRECAO = [
    (3, "Tributário (Repetição de Indébito Tributário - Manual de Cálculos da JF) — SELIC simples a partir de 01/1996"),
    (30, "Tributário => [...BTN - INPC (03/91) UFIR (01/92) - SELIC (01/96) - SEM EXPURGOS]"),
    (65, "Ações Condenatórias em Geral - Manual de Cálculos da JF (Edição 2022)"),
    (4, "Ações Condenatórias em Geral - Manual de Cálculos da JF (Edição 2020)"),
    (64, "Benefícios Previdenciários - Manual de Cálculos da JF (Edição 2022)"),
    (32, "Benefícios Previdenciários - Manual de Cálculos da JF (Edição 2020)"),
    (67, "Sem correção monetária"),
    (0, "Sem critério de Correção para Partes e Parcelas"),
    (43, "IPCA-E (1) => ORTN-OTN-BTN-INPC(03/91)-IPCA-E (02/93 em diante)"),
    (42, "IPCA-E (2) => ORTN-OTN-BTN-INPC (03/91)-IPCA-E (07/2009 em diante)"),
    (66, "IPCA-E(1) + IPCA (Lei 14.905/24) => ...IPCA-E (02/93) - IPCA (09/24)"),
    (68, "Diversos I + IPCA (Lei 14.905/24) => [...INPC (03/91) - IPCA (09/24)]"),
    (36, "Diversos I+TR(07/09)+IPCA-E => [...INPC (03/91) - TR (07/09) - IPCA-E (26/03/15)]"),
    (16, "Diversos I => [ORTN - OTN - BTN - INPC (03/91)]"),
    (18, "Diversos I+TR(07/09)"),
    (19, "Diversos I+Poupança(07/2009)"),
    (17, "Diversos II => [...BTN - INPC (03/91) - UFIR (01/92) - IPCA-E (01/00)]"),
    (20, "Diversos II+TR(07/09)"),
    (21, "Diversos II+Poupança(07/09)"),
    (38, "Diversos III => [...UFIR (01/92) - IPCA-E (01/00) - TR(07/09) - IPCA-E (26/03/15)]"),
    (15, "Taxa Referencial (TR) => [ORTN - OTN - BTN - TR (02/91)]"),
    (13, "Poupança (com juros remuneratórios)"),
    (29, "Unidade Padrão de Capital (UPC)"),
    (9, "Previdenciário I => [...INPC (07/95) - IGP-DI (05/96)]"),
    (22, "Previdenciário I+TR(07/09)"),
    (23, "Previdenciário I + Poupança(07/09)"),
    (44, "Previdenciário I+IPCA-E(07/09)"),
    (12, "Previdenciário II => [...IGP-DI (05/96) - INPC (01/04)]"),
    (24, "Previdenciário II+TR(07/09)"),
    (34, "Previdenciário II+TR(07/09)+INPC(26/03/2015)"),
    (25, "Previdenciário II+Poupança(07/09)"),
    (45, "Previdenciário II+IPCA-E(07/09)"),
    (26, "Previdenciário III => [...IGP-DI (05/96) - INPC (04/06)]"),
    (27, "Previdenciário III+TR(07/09)"),
    (28, "Previdenciário III+Poupança(07/09)"),
    (46, "Previdenciário III+IPCA-E(07/09)"),
    (47, "Previdenciário III+TR(07/09)+IPCA-E(09/17)"),
    (48, "Previdenciário III+TR(07/09)+INPC(09/17)"),
    (39, "IGP-M/FGV => ORTN - OTN - BTN - IGP-M (06/89)"),
    (40, "INCC-M/FGV => ORTN - OTN - BTN - INCC-M (06/89)"),
    (41, "INCC-DI/FGV => ORTN - OTN - BTN - INCC-DI (01/90)"),
]

JUROS = [
    ("0", "Sem Juros Moratórios"),
    ("1", "6% a.a. (0,5% ao mês)"),
    ("2", "12% a.a. (1% ao mês)"),
    ("3", "6% a.a. até 12/02 e 12% a.a."),
    ("7", "6% a.a. até 07/09 e 0%"),
    ("9", "12% a.a. até 07/09 e 0%"),
    ("11", "12% a.a. até 07/09 e Juros Poupança"),
    ("13", "6% a.a. até 07/09 e Juros Poupança"),
    ("14", "6% a.a. até 12/02, 12% a.a. até 07/09 e Juros Poupança"),
    ("15", "12% a.a. até 08/01, 6% a.a. até 07/09 e Juros Poupança"),
    ("16", "12% a.a. (1% ao mês) até 08/24 - Taxa Legal (Lei 14.905/24)"),
]

HONORARIOS_MODOS = [
    ("0", "Nenhum"),
    ("3", "Valor da Condenação"),
    ("1", "Valor da Causa ou Proveito Econômico (informar valor e data)"),
    ("2", "Valor Certo (informar valor e data)"),
    ("4", "Valor da Condenação - Sem descontos"),
    ("5", "Valor da Condenação - Descontos até... (informar considerar_ate)"),
]

UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI",
       "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]

ORIENTACAO = """\
Uso típico (a escolha do critério depende do que o título judicial determina):
- Repetição de indébito tributário: criterio_correcao=3 (Manual de Cálculos da JF, SELIC a partir
  de cada recolhimento) e juros_codigo="0" (a SELIC já engloba juros). Cada recolhimento indevido é
  uma parcela (mês/ano do pagamento e valor recolhido).
- Ações condenatórias em geral (Manual da JF, ed. 2022): criterio_correcao=65 com selic_ec113=true
  (SELIC a partir de 12/2021, EC 113/21); juros conforme o título (ex.: "1" 0,5% a.m. ou "2" 1% a.m.)
  com juros_data_inicio (ex.: citação).
- Honorários contra a Fazenda Pública: honorarios.modo="3" + escalonar_fazenda=true + faixas com os
  5 percentuais do art. 85, §3º, do CPC (ex.: [10, 8, 5, 3, 1]).
"""
