<h1 align="center">🎮 gamecal</h1>

<p align="center">
  <b>Calendário de lançamentos de games direto no terminal</b><br>
  Visual estilo <i>btop</i> · PC, PlayStation, Xbox, Nintendo e mobile · busca de jogos lançados ou não
</p>

<p align="center">
  <img src="docs/calendario.png" alt="gamecal mostrando os próximos 30 dias de lançamentos" width="100%">
</p>

## ✨ O que faz

- **Próximos lançamentos** (7, 15, 30, 60 ou 90 dias) com nome, data, contagem regressiva, plataformas, gênero, desenvolvedora e tipo (original, port, remaster, early access…).
- **Filtro por plataforma:** PC, PlayStation, Xbox, Nintendo, Mobile.
- **Painel de resumo:** lançamentos por semana e por plataforma, em barras.
- **Busca de jogos** (`/`), lançados ou ainda por lançar. Entende siglas (`gta` acha Grand Theft Auto) e ordena por popularidade.
- **Várias fontes** unidas sem duplicar o mesmo jogo.
- **Cache local**, então abre rápido e funciona bem em reaberturas.
- **Exporta para calendário `.ics`** (`e`): Apple Calendar, Google Calendar, Outlook… com lembrete na véspera às 9h.
- Abre a página do jogo no navegador (`o`).

<p align="center">
  <img src="docs/busca.png" alt="Busca de jogos no gamecal" width="100%">
</p>

## 📦 Instalação

Requisitos: **Python 3.10+**, internet e um terminal com cores e Unicode (macOS, Linux, Windows Terminal).

```bash
# recomendado: isola as dependências
pipx install git+https://github.com/engjoaofaro/gamecal

# ou com pip
pip install git+https://github.com/engjoaofaro/gamecal
```

Depois, em qualquer pasta:

```bash
gamecal
```

Atualizar: `pipx upgrade gamecal` · Remover: `pipx uninstall gamecal`.

<details>
<summary>Rodar a partir do código-fonte</summary>

```bash
git clone https://github.com/engjoaofaro/gamecal && cd gamecal
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/gamecal
```
</details>

## ⌨️ Atalhos

| Tecla | Ação |
|---|---|
| `/` | Buscar jogo (Enter confirma, `Esc` volta ao calendário) |
| `r` | Atualizar, ignorando o cache |
| `d` | Alternar a janela: 7 → 15 → 30 → 60 → 90 dias |
| `c` | Alternar entre só **curados** e **todos** (inclui jogos que só a Steam lista) |
| `e` | Exportar **todos os jogos da lista visível** (respeita janela, filtros e busca) para `.ics` |
| `E` | Exportar só o jogo selecionado |
| `o` | Abrir a página do jogo selecionado |
| `↑` `↓` | Navegar na lista |
| `Tab` + `Espaço` | Marcar/desmarcar plataformas no filtro |
| `q` | Sair |

## 🔤 Fonte recomendada

O app roda no seu terminal, então a fonte é a do seu terminal. O visual dos screenshots usa a
**[Monaspace Krypton](https://monaspace.githubnext.com/)** (GitHub, licença OFL), que combina bem com o clima "game":

```bash
brew install --cask font-monaspace        # macOS
```

Depois, escolha `Monaspace Krypton` nas configurações de fonte do seu terminal (Ghostty, iTerm2, WezTerm, Kitty, Windows Terminal…).
Uma fonte monoespaçada com emojis e ícones funciona bem também; sem a Krypton, tudo continua utilizável.

## 📅 Exportar para o calendário

Aperte `e` para gerar um arquivo `.ics` com os jogos que estão na tela (na pasta `~/Downloads`, ou na sua home se ela não existir). `E` exporta só o jogo selecionado.
Cada jogo vira um evento de **dia inteiro**, com plataformas, gênero, dev/publisher e link na descrição, e um lembrete às 9h do dia anterior.
O arquivo é aceito por Apple Calendar, Google Calendar, Outlook e similares: dê dois cliques ou importe no app.
Jogos sem data exata (só "Q4", "TBA") não são exportados. Reimportar o mesmo arquivo não duplica eventos, porque cada evento tem ID estável.

## 🌐 Fontes de dados

| Fonte | Chave | Cobre |
|---|---|---|
| **Wikipedia** (listas de jogos lançados por ano) | não precisa | Multiplataforma, com gênero, dev e publisher |
| **Steam** (loja) | não precisa | PC, com datas exatas de "em breve" e busca com detalhes |
| **RAWG** | opcional | Catálogo enorme (jogos de todas as épocas e plataformas). Melhora muito a busca; no calendário contribui com poucos itens futuros |

Para ativar a RAWG, crie uma chave grátis em <https://rawg.io/apidocs> e use **uma** das opções:

```bash
# opção 1: variável de ambiente (ponha no ~/.zshrc ou ~/.bashrc para ficar permanente)
export RAWG_API_KEY="sua-chave"

# opção 2: arquivo de configuração
mkdir -p ~/.config/gamecal && echo "sua-chave" > ~/.config/gamecal/rawg_key && chmod 600 ~/.config/gamecal/rawg_key
```

A chave fica só na sua máquina, e o gamecal nunca a grava no cache nem em arquivos exportados. Se a chave for inválida, o painel **Fontes** mostra `erro`.

### Busca

A busca combina as três fontes e une o mesmo jogo numa linha só (plataformas e fontes somadas). Os resultados vêm ordenados por popularidade (campo `added` da RAWG), para que
Breath of the Wild apareça antes de jogos amadores com nome parecido. Nomes e siglas são aceitos: `gta vi`, `mario kart`, `hollow knight`.

O painel **Fontes** mostra o estado de cada uma (`ok · quantidade` ou `erro`).
O cache fica em `~/.cache/gamecal` (Wikipedia: 6h, Steam: 1h, RAWG: 3h).

### "Curados" vs "todos"

A Steam lista centenas de jogos pequenos por semana. Por padrão o calendário mostra só os "curados", ou seja, os que aparecem
na Wikipedia ou na RAWG. Os demais ficam ocultos e o painel avisa quantos são (`+601 só-Steam ocultos`). Aperte `c` para ver tudo.

## ⚠️ Limitações

- Os dados da Wikipedia e da Steam são lidos do HTML/APIs públicas. Se o formato mudar, uma fonte pode falhar e o painel **Fontes** vai mostrar `erro`.
- Jogos da Wikipedia sem dia exato (só "Q4", "December" ou "TBA") não entram no calendário, mas aparecem na busca.
- Sem chave RAWG, a busca de jogos antigos cobre só a Steam e as listas da Wikipedia (ano anterior, atual e próximo). Com a chave, a busca traz também clássicos de consoles antigos (ex.: toda a série Zelda).
- As datas podem variar por região e mudar com adiamentos. Confira na página oficial antes de reservar.
- Testado em macOS. Linux e Windows devem funcionar, mas não foram verificados.

## 🛠️ Desenvolvimento

O app inteiro está em um único arquivo, [`gamecal.py`](gamecal.py): parsers das fontes, mesclagem e a interface em [Textual](https://textual.textualize.io).
Dependências: `textual` e `httpx`.

Ideias para o futuro: notificações de lançamento, mais fontes (IGDB, Nintendo, PlayStation Store), temas.
Pull requests são bem-vindos.

## 📄 Licença

[MIT](LICENSE)
