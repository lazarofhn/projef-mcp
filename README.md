# projef-mcp

Servidor [MCP](https://modelcontextprotocol.io) que leva o **[Projef Web](https://www.jfrs.jus.br/projefweb/)**,
a calculadora judicial da Justiça Federal do Rio Grande do Sul, para dentro do Claude (e de qualquer
cliente MCP). Você descreve o cálculo em linguagem natural e recebe os números estruturados, parcela a
parcela, e o link do demonstrativo oficial em PDF, sem abrir o navegador.

Feito para os cálculos mais comuns na Justiça Federal:

- **Repetição de indébito tributário**: Selic a partir de cada recolhimento, pelo Manual de Cálculos da JF;
- **Ações condenatórias em geral**: correção pelo Manual de Cálculos da JF (edição 2022) e Selic a partir de 12/2021 (EC 113/21);
- **Honorários de sucumbência**, inclusive escalonados pelas faixas do art. 85, §3º, do CPC quando a Fazenda Pública é parte.

> **Aviso.** Projeto independente, **sem vínculo com a JFRS, o TRF4 ou a Justiça Federal**. O cálculo é
> feito pelo próprio Projef Web, nos servidores da JFRS; este MCP só preenche o formulário e lê o
> resultado. Vale a ressalva do próprio Projef: o programa é uma sugestão de cálculo, prevalece sempre o
> entendimento de cada Juízo, e a escolha dos critérios é responsabilidade de quem usa. Confira o
> demonstrativo antes de usá-lo num processo.

## Exemplo

> Calcule a repetição de indébito de recolhimentos de R$ 1.500,00 em 03/2021, R$ 2.000,50 em 04/2021 e
> R$ 1.800,25 em 05/2021, atualizado até 11/2026, para a CONTRIBUINTE TESTE LTDA (CNPJ 11.222.333/0001-81),
> com honorários sobre a condenação escalonados contra a Fazenda (10%, 8%, 5%, 3%, 1%).

O Claude chama `projef_calcular` e responde com o total da conta, a composição (principal corrigido,
Selic, honorários), a tabela por parcela e o link do PDF oficial, por exemplo
`https://www.jfrs.jus.br/projefweb/app/relatorio?id=544240e0`.

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `projef_opcoes` | Lista os critérios de correção monetária, as taxas de juros moratórios e os modos de honorários aceitos, com orientação de uso. |
| `projef_calcular` | Faz o cálculo e devolve o identificador, o link do PDF, o resumo por parte, as sucumbências, o total da conta, os critérios aplicados e o demonstrativo parcela a parcela (principal, coeficiente de correção, principal corrigido, juros, Selic em % e em R$, total). Leva de 15 a 40 segundos. |
| `projef_recuperar` | Recupera um cálculo já feito a partir do identificador impresso no rodapé do PDF (válido por 3 anos). Não usa navegador. |

Com `incluir_pdf=true`, o PDF vai anexado na resposta; com `incluir_texto=true`, vai também o texto
integral do demonstrativo.

## Instalação

Requer Python 3.10 ou superior. Na primeira execução o MCP baixa o Chromium usado pelo Playwright
(cerca de 150 MB), então o primeiro cálculo demora um pouco mais.

### Claude Desktop (com uv)

Instale o [uv](https://docs.astral.sh/uv/) e acrescente ao `claude_desktop_config.json`
(Configurações → Desenvolvedor → Editar configuração):

```json
{
  "mcpServers": {
    "projef": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/lazarofhn/projef-mcp", "projef-mcp"]
    }
  }
}
```

Reinicie o Claude Desktop.

### Com pip

```bash
pip install git+https://github.com/lazarofhn/projef-mcp
python -m playwright install chromium
```

E no `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "projef": { "command": "projef-mcp" }
  }
}
```

No Windows, se o comando não for encontrado, use o caminho completo do Python com
`"args": ["-m", "projef_mcp"]`.

## Uso remoto (claude.ai, celular, equipe)

Para usar no claude.ai (web, celular) ou compartilhar com colegas, rode o servidor em modo HTTP numa
máquina sempre ligada e publique-o num domínio com HTTPS. Depois, cada pessoa adiciona a URL em
**Configurações → Conectores → Adicionar conector personalizado**.

```bash
PROJEF_PATH_SECRET=um-segredo-longo PROJEF_ALLOWED_HOSTS=projef.seudominio.com.br projef-mcp --http --port 8092
```

| Variável | Para quê |
|---|---|
| `PROJEF_PATH_SECRET` | Segmento secreto no caminho: a URL vira `https://host/<segredo>/mcp`. Sem ele, qualquer caminho responde 404. O Claude não aceita token na query string, por isso o segredo vai no caminho. |
| `PROJEF_ALLOWED_HOSTS` | Domínios aceitos no cabeçalho `Host` (proteção contra DNS rebinding); outros recebem 421. |
| `PROJEF_CONCORRENCIA` | Máximo de cálculos simultâneos (padrão 2), para não sobrecarregar o serviço da JFRS. |
| `PROJEF_HOST`, `PROJEF_PORT` | Endereço e porta (padrão `127.0.0.1:8092`). |

Para trocar o acesso de todos, mude `PROJEF_PATH_SECRET` e reinicie; cada pessoa adiciona a URL nova.

**Servidor Linux com systemd:** `PROJEF_HOSTNAME=projef.seudominio.com.br bash deploy/instalar.sh` cria o
ambiente, gera o segredo em `.env`, instala o serviço `projef-mcp` e mostra a URL final.

**Docker:**

```bash
docker build -t projef-mcp .
docker run -d -p 127.0.0.1:8092:8092 \
  -e PROJEF_PATH_SECRET=um-segredo-longo -e PROJEF_ALLOWED_HOSTS=projef.seudominio.com.br projef-mcp
```

**Publicar a porta:** um [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
com domínio próprio funciona bem com os conectores do Claude: acrescente ao `config.yml` do túnel
`hostname: projef.seudominio.com.br` → `service: http://localhost:8092` e crie o DNS com
`cloudflared tunnel route dns <túnel> projef.seudominio.com.br`. Túneis temporários (URL que muda a cada
execução) não servem para conectores.

## Como funciona

O Projef Web é uma aplicação GWT/Ext JS em que o navegador só coleta os dados: o cálculo é feito no
servidor da JFRS quando o cálculo é gravado, e o resultado sai como PDF em
`/projefweb/app/relatorio?id=<identificador>`. O MCP:

1. abre o Projef num Chromium invisível (Playwright) e preenche as abas: dados do processo, correção
   monetária, juros, partes e parcelas (pela opção "Colar de Planilha"), honorários e dados finais;
2. clica em **Calcular** e lê o identificador devolvido;
3. baixa o PDF por HTTP e o converte em dados estruturados (`pypdf`).

Recalcular localmente exigiria reimplementar o Manual de Cálculos com todas as séries de índices, e o
resultado poderia divergir do oficial; por isso o MCP usa o motor da própria JFRS.

## Política de privacidade

- **Dados coletados:** só os que você informa para o cálculo (nomes, CPF/CNPJ, número do processo,
  datas e valores das parcelas, honorários, dados do confeccionador). O MCP não lê histórico de
  conversa, memória nem arquivos do usuário.
- **Uso:** os dados servem apenas para preencher o formulário do Projef Web e montar a resposta.
- **Compartilhamento com terceiros:** os dados são enviados ao Projef Web, da Justiça Federal do Rio
  Grande do Sul, exatamente como quando se usa o site. Com `gerar_sicar=true`, o número do processo
  também é consultado no eproc da 4ª Região, que preenche autor e réu com os dados reais do processo
  (desligado por padrão). Nada é enviado a outros serviços.
- **Armazenamento e retenção:** o MCP não guarda dados: nada fica em disco nem em banco de dados, e o
  navegador invisível é descartado a cada cálculo. A JFRS grava cada cálculo e permite recuperá-lo pelo
  identificador durante 3 anos; o link do PDF é público para quem tiver o identificador. Quem hospeda uma
  instância remota pode ter registros de acesso do próprio servidor web (endereço, horário, caminho),
  sem o conteúdo dos cálculos.
- **Contato:** abra uma [issue](https://github.com/lazarofhn/projef-mcp/issues) neste repositório.

## Uso responsável

O MCP limita os cálculos simultâneos e não faz consultas em massa. Use com moderação: é um serviço
público mantido pela JFRS.

## Conformidade com os conectores do Claude

- Cada ferramenta declara `title`, `readOnlyHint`, `destructiveHint`, `idempotentHint` e
  `openWorldHint`. Leitura (`projef_opcoes`, `projef_recuperar`) e escrita (`projef_calcular`, que cria
  um registro novo na JFRS) ficam em ferramentas separadas.
- Os erros voltam como erro de ferramenta (`isError`), com a causa e o que fazer.
- Os resultados ficam abaixo de ~140 mil caracteres (limite do claude.ai: ~150 mil). Demonstrativos muito
  longos são resumidos, com aviso e o link do PDF completo. O cálculo é interrompido aos 200 segundos (o
  claude.ai encerra a chamada aos 240).
- No modo remoto, o acesso é por URL com caminho secreto (para o Claude, um conector sem autenticação).
  Serve bem como conector personalizado. Não se presta ao diretório oficial de conectores da Anthropic,
  que exige que o servidor seja do dono do serviço que ele acessa; aqui o serviço é da JFRS.

## Limitações

- Depende da tela atual do Projef Web (versão 3.42.11, novembro de 2026). Se a JFRS mudar o layout, o
  preenchimento pode quebrar até ser ajustado; abra uma issue.
- Ainda não cobre as abas "Outras Sucumbências" (custas, honorários periciais, deduções), PSS, descontos
  por parte e honorários na fase de cumprimento.
- Os quadros de honorários escalonados e de RRA vêm como texto (`demonstrativo_honorarios_texto`,
  `rra_texto`), não em tabela.

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest                    # testes offline (parser e validações)
PROJEF_ONLINE=1 pytest    # inclui um cálculo real no Projef Web
```

## Licença

[MIT](LICENSE).
