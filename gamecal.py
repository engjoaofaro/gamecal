#!/usr/bin/env python3
"""gamecal — calendário de lançamentos de games no terminal (estilo btop).

Fontes:
  • Wikipedia  (sem chave) — multiplataforma, com gênero/dev/publisher
  • Steam      (sem chave) — PC, datas exatas da loja
  • RAWG       (opcional)  — defina RAWG_API_KEY (grátis em rawg.io/apidocs)

Teclas: / buscar · r atualizar · d janela (7/15/30/60/90 dias) · c só curados
        o abrir página · esc limpar busca · q sair
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import httpx
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, SelectionList, Static

UA = "gamecal/1.0 (https://example.org/gamecal)"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gamecal"
RAWG_KEY = os.environ.get("RAWG_API_KEY", "")
WINDOWS = [7, 15, 30, 60, 90]
DOW = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MON_PT = "jan fev mar abr mai jun jul ago set out nov dez".split()

PLATFORM_NAMES = {
    "WIN": "PC", "OSX": "Mac", "LIN": "Linux", "NS": "Switch", "NS2": "Switch 2",
    "PS3": "PS3", "PS4": "PS4", "PS5": "PS5", "PSVR2": "PS VR2", "PSV": "Vita",
    "XBX/S": "Xbox Series", "XBO": "Xbox One", "X360": "Xbox 360", "AND": "Android", "DROID": "Android",
    "IOS": "iOS", "WII": "Wii", "WIIU": "Wii U", "3DS": "3DS", "QUEST": "Quest",
}
GROUPS = ["PC", "PlayStation", "Xbox", "Nintendo", "Mobile", "Outros"]
GROUP_COLOR = {"PC": "#f5c542", "PlayStation": "#4f8cff", "Xbox": "#3ddc84",
               "Nintendo": "#ff5c5c", "Mobile": "#c678dd", "Outros": "#8b949e"}


def group_of(p: str) -> str:
    s = p.lower()
    if s in ("pc", "mac", "linux", "windows", "macos") or "pc" in s.split():
        return "PC"
    if "ps" in s or "playstation" in s or "vita" in s:
        return "PlayStation"
    if "xbox" in s:
        return "Xbox"
    if any(k in s for k in ("switch", "nintendo", "wii", "3ds")):
        return "Nintendo"
    if s in ("android", "ios") or "mobile" in s:
        return "Mobile"
    return "Outros"


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass
class Game:
    name: str
    date: str | None = None          # ISO yyyy-mm-dd quando o dia é exato
    date_text: str = ""              # texto original ("Q4", "December"…)
    platforms: list[str] = field(default_factory=list)
    kind: str = ""
    genre: str = ""
    dev: str = ""
    pub: str = ""
    url: str = ""
    sources: list[str] = field(default_factory=list)

    @property
    def d(self) -> date | None:
        return date.fromisoformat(self.date) if self.date else None

    @property
    def groups(self) -> set[str]:
        return {group_of(p) for p in self.platforms} or {"Outros"}

    @property
    def curated(self) -> bool:
        return any(s != "Steam" for s in self.sources)


# ───────────────────────────── cache ─────────────────────────────
def cache_get(key: str, ttl: int, force: bool = False) -> list[Game] | None:
    f = CACHE / f"{key}.json"
    if force or not f.exists() or time.time() - f.stat().st_mtime > ttl:
        return None
    try:
        return [Game(**g) for g in json.loads(f.read_text())]
    except Exception:
        return None


def cache_put(key: str, games: list[Game]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{key}.json").write_text(json.dumps([asdict(g) for g in games]))


# ───────────────────────────── Wikipedia ─────────────────────────────
class TableParser(HTMLParser):
    """Extrai tabelas 'wikitable' como listas de células (texto, href)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[tuple[str, str]]]] = []
        self._stack: list[list | None] = []
        self._row: list | None = None
        self._cell: dict | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            wt = "wikitable" in (a.get("class") or "")
            self._stack.append([] if wt else None)
        elif not self._stack or self._stack[-1] is None:
            return
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            span = int(re.sub(r"\D", "", a.get("colspan", "1")) or 1)
            self._cell = {"t": [], "href": "", "span": span}
        elif tag == "a" and self._cell and not self._cell["href"]:
            self._cell["href"] = a.get("href", "")
        elif tag in ("sup", "style", "script"):
            self._skip += 1
        elif tag == "br" and self._cell:
            self._cell["t"].append(" ")

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            t = self._stack.pop()
            if t:
                self.tables.append(t)
        elif not self._stack or self._stack[-1] is None:
            return
        elif tag in ("sup", "style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            txt = re.sub(r"\s+", " ", "".join(self._cell["t"])).strip()
            self._row.extend([(txt, self._cell["href"])] * self._cell["span"])
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._stack[-1].append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell["t"].append(data)


def parse_wiki_date(txt: str, year: int) -> tuple[str | None, str]:
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\b", txt)
    if m and m.group(1).lower() in MONTHS:
        try:
            return date(year, MONTHS[m.group(1).lower()], int(m.group(2))).isoformat(), txt
        except ValueError:
            pass
    return None, txt


def parse_wiki(html: str, year: int) -> list[Game]:
    p = TableParser()
    p.feed(html)
    out: list[Game] = []
    for tbl in p.tables:
        if not tbl:
            continue
        hdr = [c[0].lower() for c in tbl[0]]
        idx = {}
        for i, h in enumerate(hdr):
            for k in ("release date", "approximate date", "title", "platform", "type", "genre",
                      "developer", "publisher"):
                if h.startswith(k) and k not in idx:
                    idx[k] = i
        dcol = idx.get("release date", idx.get("approximate date"))
        if "title" not in idx or dcol is None:
            continue
        for row in tbl[1:]:
            if len(row) <= max(idx.values()):
                continue
            g = lambda k: row[idx[k]][0] if k in idx else ""
            title = re.sub(r"\s*\((?:[A-Z]{2,3}(?:,\s*)?)+\)\s*$", "", g("title")).strip()
            if not title:
                continue
            iso, dtxt = parse_wiki_date(row[dcol][0], year)
            plats = [PLATFORM_NAMES.get(c.strip(), c.strip())
                     for c in g("platform").split(",") if c.strip()]
            href = row[idx["title"]][1]
            out.append(Game(
                name=title, date=iso, date_text=dtxt or "TBA", platforms=plats,
                kind=g("type"), genre=g("genre"), dev=g("developer"), pub=g("publisher"),
                url=("https://en.wikipedia.org" + href) if href.startswith("/wiki/") else "",
                sources=["Wikipedia"]))
    return out


async def fetch_wiki(c: httpx.AsyncClient, year: int, force=False) -> list[Game]:
    key = f"wiki_{year}"
    if (cached := cache_get(key, 6 * 3600, force)) is not None:
        return cached
    for title in (f"List_of_video_games_released_in_{year}",
                  f"List_of_video_games_scheduled_for_release_in_{year}"):
        r = await c.get("https://en.wikipedia.org/w/api.php", params={
            "action": "parse", "page": title, "prop": "text", "format": "json",
            "formatversion": 2})
        r.raise_for_status()
        j = r.json()
        if "parse" in j:
            games = await asyncio.to_thread(parse_wiki, j["parse"]["text"], year)
            cache_put(key, games)
            return games
    return cache_get(key, 10**9) or []


# ───────────────────────────── Steam ─────────────────────────────
def parse_steam_date(txt: str) -> str | None:
    txt = txt.strip()
    for fmt in ("%d %b, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(txt, fmt).date().isoformat()
        except ValueError:
            pass
    return None


STEAM_PLAT = {"win": "PC", "mac": "Mac", "linux": "Linux"}


async def fetch_steam_upcoming(c: httpx.AsyncClient, force=False, pages=10) -> list[Game]:
    if (cached := cache_get("steam", 3600, force)) is not None:
        return cached

    async def page(i: int) -> str:
        r = await c.get("https://store.steampowered.com/search/results/", params={
            "query": "", "start": i * 100, "count": 100, "filter": "comingsoon",
            "sort_by": "Released_ASC", "infinite": 1, "cc": "br", "l": "english"})
        return r.json().get("results_html", "")

    htmls = await asyncio.gather(*(page(i) for i in range(pages)), return_exceptions=True)
    out: list[Game] = []
    row_re = re.compile(r'<a href="(https://store\.steampowered\.com/app/(\d+)/[^"?]*)[^>]*>(.*?)</a>', re.S)
    for h in htmls:
        if isinstance(h, Exception):
            continue
        for m in row_re.finditer(h):
            body = m.group(3)
            t = re.search(r'class="title">(.*?)</span>', body, re.S)
            rel = re.search(r'search_released[^>]*>\s*(.*?)\s*</div>', body, re.S)
            if not t:
                continue
            plats = [STEAM_PLAT[x] for x in re.findall(r"platform_img (\w+)", body) if x in STEAM_PLAT]
            txt = rel.group(1) if rel else ""
            out.append(Game(name=re.sub(r"<[^>]+>", "", t.group(1)).strip(),
                            date=parse_steam_date(txt), date_text=txt or "TBA",
                            platforms=plats or ["PC"], url=m.group(1), sources=["Steam"]))
    if out:
        cache_put("steam", out)
    return out


async def steam_search(c: httpx.AsyncClient, q: str) -> list[Game]:
    r = await c.get("https://store.steampowered.com/api/storesearch/",
                    params={"term": q, "cc": "br", "l": "english"})
    ids = [i["id"] for i in r.json().get("items", [])][:8]

    async def det(i: int) -> Game | None:
        try:
            j = (await c.get("https://store.steampowered.com/api/appdetails",
                             params={"appids": i, "cc": "br", "l": "english"})).json()[str(i)]
            if not j.get("success"):
                return None
            d = j["data"]
            if d.get("type") != "game":
                return None
            rd = d.get("release_date", {}).get("date", "")
            pl = d.get("platforms", {})
            return Game(
                name=d["name"], date=parse_steam_date(rd),
                date_text=rd or "TBA",
                platforms=[n for k, n in (("windows", "PC"), ("mac", "Mac"), ("linux", "Linux")) if pl.get(k)],
                genre=", ".join(x["description"] for x in d.get("genres", [])[:3]),
                dev=", ".join(d.get("developers", [])[:2]), pub=", ".join(d.get("publishers", [])[:2]),
                url=f"https://store.steampowered.com/app/{i}", sources=["Steam"])
        except Exception:
            return None

    return [g for g in await asyncio.gather(*(det(i) for i in ids)) if g]


# ───────────────────────────── RAWG (opcional) ─────────────────────────────
def rawg_to_game(j: dict) -> Game:
    plats = [p["platform"]["name"] for p in j.get("platforms") or []]
    return Game(name=j["name"], date=j.get("released"), date_text=j.get("released") or "TBA",
                platforms=plats, genre=", ".join(g["name"] for g in j.get("genres", [])[:3]),
                url=f"https://rawg.io/games/{j.get('slug', '')}", sources=["RAWG"])


async def fetch_rawg(c: httpx.AsyncClient, start: date, end: date, force=False) -> list[Game]:
    if not RAWG_KEY:
        return []
    key = f"rawg_{start}_{end}"
    if (cached := cache_get(key, 3 * 3600, force)) is not None:
        return cached
    out: list[Game] = []
    for pg in (1, 2, 3, 4, 5):
        r = await c.get("https://api.rawg.io/api/games", params={
            "key": RAWG_KEY, "dates": f"{start},{end}", "ordering": "released",
            "page_size": 40, "page": pg})
        if r.status_code != 200:
            break
        j = r.json()
        out += [rawg_to_game(x) for x in j.get("results", [])]
        if not j.get("next"):
            break
    cache_put(key, out)
    return out


async def rawg_search(c: httpx.AsyncClient, q: str) -> list[Game]:
    if not RAWG_KEY:
        return []
    r = await c.get("https://api.rawg.io/api/games", params={
        "key": RAWG_KEY, "search": q, "page_size": 15, "search_precise": "true"})
    return [rawg_to_game(x) for x in r.json().get("results", [])] if r.status_code == 200 else []


# ───────────────────────────── merge ─────────────────────────────
def merge(*lists: list[Game]) -> list[Game]:
    by: dict[str, list[Game]] = {}
    for lst in lists:
        for g in lst:
            bucket = by.setdefault(norm(g.name), [])
            for e in bucket:
                if (e.d is None or g.d is None or abs((e.d - g.d).days) <= 1):
                    for p in g.platforms:
                        if p not in e.platforms:
                            e.platforms.append(p)
                    for s in g.sources:
                        if s not in e.sources:
                            e.sources.append(s)
                    for a in ("genre", "dev", "pub", "kind", "url"):
                        if not getattr(e, a) and getattr(g, a):
                            setattr(e, a, getattr(g, a))
                    if e.d is None and g.d:
                        e.date, e.date_text = g.date, g.date_text
                    break
            else:
                bucket.append(g)
    return [g for b in by.values() for g in b]


# ───────────────────────────── UI ─────────────────────────────
def rel_days(d: date | None, today: date) -> Text:
    if d is None:
        return Text("—", style="dim")
    n = (d - today).days
    if n == 0:
        return Text("HOJE", style="bold black on #3ddc84")
    if n == 1:
        return Text("amanhã", style="bold #3ddc84")
    if n > 0:
        return Text(f"em {n}d", style="#3ddc84" if n <= 7 else "#58a6ff" if n <= 14 else "#8b949e")
    return Text(f"há {-n}d", style="dim #d29922")


def plat_badges(g: Game) -> Text:
    t = Text()
    seen = set()
    for p in g.platforms:
        if p in seen:
            continue
        seen.add(p)
        t.append(p, style=GROUP_COLOR[group_of(p)])
        t.append(" · ", style="dim")
    t.rstrip()
    if t.plain.endswith("·"):
        t.right_crop(1)
        t.rstrip()
    return t


class GameCal(App):
    TITLE = "gamecal"
    CSS = """
    Screen { background: #0d1117; color: #c9d1d9; }
    #top { height: 3; border: round #58a6ff; padding: 0 1; content-align: left middle; }
    #side { width: 30; }
    #plat { height: 9; border: round #f5c542; background: #0d1117; padding: 0 1; }
    #plat > .selection-list--button { color: #8b949e; }
    #stats { height: 1fr; border: round #3ddc84; padding: 0 1; }
    #srcs { height: 7; border: round #c678dd; padding: 0 1; }
    #content { width: 1fr; }
    #search { display: none; border: round #d29922; background: #0d1117; }
    #table { height: 1fr; border: round #4f8cff; background: #0d1117; }
    #table > .datatable--header { background: #161b22; color: #58a6ff; text-style: bold; }
    #table > .datatable--cursor { background: #1f6feb 40%; }
    #table > .datatable--even-row { background: #10151c; }
    #detail { height: 8; border: round #ff5c5c; padding: 0 1; }
    Footer { background: #161b22; }
    """
    BINDINGS = [
        Binding("slash", "search", "Buscar"),
        Binding("r", "refresh", "Atualizar"),
        Binding("d", "window", "Janela"),
        Binding("c", "curated", "Só curados"),
        Binding("o", "open", "Abrir"),
        Binding("escape", "clear", "Limpar", show=False),
        Binding("q", "quit", "Sair"),
    ]

    def __init__(self):
        super().__init__()
        self.today = date.today()
        self.win_i = 2
        self.curated_only = True
        self.pool: list[Game] = []        # tudo carregado (calendário + busca local)
        self.view: list[Game] = []
        self.search_results: list[Game] | None = None
        self.status: dict[str, str] = {}
        self.extra_years_loaded = False
        self.client: httpx.AsyncClient | None = None

    # ── layout
    def compose(self) -> ComposeResult:
        yield Static(id="top")
        with Horizontal():
            with Vertical(id="side"):
                yield SelectionList(*[(Text(g, style=GROUP_COLOR[g]), g, True) for g in GROUPS], id="plat")
                yield Static(id="stats")
                yield Static(id="srcs")
            with Vertical(id="content"):
                yield Input(placeholder="buscar jogo (lançado ou não)… Enter confirma, Esc cancela", id="search")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
                yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#plat").border_title = "Plataformas"
        self.query_one("#stats").border_title = "Resumo"
        self.query_one("#srcs").border_title = "Fontes"
        self.query_one("#detail").border_title = "Detalhes"
        t = self.query_one("#table", DataTable)
        for label, w in (("Data", 11), ("Quando", 8), ("Jogo", 40), ("Tipo", 12),
                         ("Plataformas", 38), ("Gênero", 24), ("Desenvolvedora", 24)):
            t.add_column(label, width=w)
        t.focus()
        self.set_interval(1, self.tick)
        self.client = httpx.AsyncClient(headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
        self.load(force=False)

    def tick(self) -> None:
        now = datetime.now()
        if now.date() != self.today:
            self.today = now.date()
            self.render_table()
        self.render_top()

    # ── dados
    @property
    def window(self) -> int:
        return WINDOWS[self.win_i]

    def load(self, force: bool) -> None:
        self.run_worker(self._load(force), exclusive=True, group="load")

    async def _load(self, force: bool) -> None:
        end = self.today + timedelta(days=WINDOWS[-1])
        years = sorted({self.today.year, end.year})
        self.status = {"Wikipedia": "…", "Steam": "…", "RAWG": "…" if RAWG_KEY else "sem chave"}
        self.render_srcs()

        async def run(name, coro):
            try:
                r = await coro
                prev = self.status.get(name, "")
                n = len(r) + (int(prev.split("· ")[1]) if name == "Wikipedia" and "· " in prev else 0)
                self.status[name] = f"ok · {n}"
                return r
            except Exception as e:  # noqa: BLE001
                self.status[name] = f"erro: {type(e).__name__}"
                return []
            finally:
                self.render_srcs()

        c = self.client
        wikis = [run("Wikipedia", fetch_wiki(c, y, force)) for y in years]
        res = await asyncio.gather(*wikis, run("Steam", fetch_steam_upcoming(c, force)),
                                   run("RAWG", fetch_rawg(c, self.today, end, force)))
        wiki = [g for r in res[:len(years)] for g in r]
        self.pool = merge(wiki, res[-2], res[-1])
        self.render_table()

    # ── render
    def render_top(self) -> None:
        now = datetime.now()
        t = Text()
        t.append(" 🎮 GAMECAL ", style="bold #0d1117 on #58a6ff")
        if self.search_results is None:
            t.append(f"  próximos {self.window} dias", style="bold")
            t.append(f"   {'curados' if self.curated_only else 'todos (inclui Steam)'}", style="#d29922")
        else:
            t.append("  🔎 modo busca", style="bold #ff5c5c")
        t.append(f"   {len(self.view)} jogos", style="#3ddc84")
        t.append(f"    {DOW[now.weekday()]} {now:%d/%m/%Y %H:%M:%S}", style="dim")
        self.query_one("#top", Static).update(t)

    def render_srcs(self) -> None:
        t = Text()
        for n in ("Wikipedia", "Steam", "RAWG"):
            s = self.status.get(n, "")
            col = "#3ddc84" if s.startswith("ok") else "#f85149" if s.startswith("erro") else "#d29922"
            t.append(f"{n:<10}", style="bold")
            t.append(s + "\n", style=col)
        self.query_one("#srcs", Static).update(t)

    def selected_groups(self) -> set[str]:
        return set(self.query_one("#plat", SelectionList).selected)

    def compute_view(self) -> list[Game]:
        if self.search_results is not None:
            return self.search_results
        end = self.today + timedelta(days=self.window)
        groups = self.selected_groups()
        out = [g for g in self.pool
               if g.d and self.today <= g.d <= end
               and (g.curated or not self.curated_only)
               and g.groups & groups]
        out.sort(key=lambda g: (g.date, norm(g.name)))
        return out

    def render_table(self) -> None:
        self.view = self.compute_view()
        t = self.query_one("#table", DataTable)
        t.clear()
        for i, g in enumerate(self.view):
            d = g.d
            when = f"{d:%d} {MON_PT[d.month - 1]} {DOW[d.weekday()]}" if d else g.date_text
            style = "bold" if d and (d - self.today).days <= 7 and (d - self.today).days >= 0 else ""
            t.add_row(Text(when, style="#58a6ff" if d else "dim"), rel_days(d, self.today),
                      Text(g.name, style=style or "#e6edf3"),
                      Text((g.kind or "")[:12], style="dim"), plat_badges(g),
                      Text(g.genre[:28], style="#8b949e"), Text((g.dev or g.pub)[:26], style="dim"),
                      key=str(i))
        t.border_title = ("Resultados da busca" if self.search_results is not None
                          else f"Lançamentos · {self.today:%d/%m} → "
                               f"{self.today + timedelta(days=self.window):%d/%m}")
        self.render_stats()
        self.render_top()
        self.show_detail(0)

    def render_stats(self) -> None:
        v = self.view
        t = Text()
        if self.search_results is not None:
            t.append(f"{len(v)} resultado(s)\n", style="bold")
            t.append("Esc volta ao calendário", style="dim")
            self.query_one("#stats", Static).update(t)
            return
        t.append(f"{len(v)}", style="bold #3ddc84")
        t.append(" lançamentos\n")
        today_n = sum(1 for g in v if g.d == self.today)
        w1 = sum(1 for g in v if g.d and (g.d - self.today).days <= 7)
        t.append(f"hoje {today_n} · 7d {w1}\n\n", style="dim")
        weeks = max(1, -(-self.window // 7))
        counts = [0] * weeks
        for g in v:
            counts[min(weeks - 1, (g.d - self.today).days // 7)] += 1
        mx = max(counts) or 1
        t.append("Por semana\n", style="bold #58a6ff")
        for i, n in enumerate(counts[:9]):
            bar = "█" * round(n / mx * 12)
            t.append(f"S{i + 1} ", style="dim")
            t.append(f"{bar:<12}", style="#58a6ff")
            t.append(f" {n}\n")
        t.append("\nPor plataforma\n", style="bold #f5c542")
        for grp in GROUPS[:-1]:
            n = sum(1 for g in v if grp in g.groups)
            t.append(f"{grp:<12}", style=GROUP_COLOR[grp])
            t.append(f"{n}\n")
        hidden = 0
        if self.curated_only:
            end = self.today + timedelta(days=self.window)
            hidden = sum(1 for g in self.pool if not g.curated and g.d and self.today <= g.d <= end)
        if hidden:
            t.append(f"\n+{hidden} só-Steam ocultos\n(tecla c)", style="dim")
        self.query_one("#stats", Static).update(t)

    def show_detail(self, i: int) -> None:
        box = self.query_one("#detail", Static)
        if not self.view or i >= len(self.view):
            box.update(Text("Nada encontrado.", style="dim"))
            return
        g = self.view[i]
        t = Text()
        t.append(g.name + "\n", style="bold #e6edf3")
        d = g.d
        t.append("Data: ", style="dim")
        t.append((f"{d:%d/%m/%Y} ({DOW[d.weekday()]})" if d else g.date_text) + "  ")
        t.append_text(rel_days(d, self.today))
        t.append("\nPlataformas: ", style="dim")
        t.append_text(plat_badges(g))
        t.append("\nGênero: ", style="dim")
        t.append(f"{g.genre or '—'}" + (f"  [{g.kind}]" if g.kind else ""))
        t.append("\nDev: ", style="dim")
        t.append(g.dev or "—")
        t.append("   Pub: ", style="dim")
        t.append(g.pub or "—")
        t.append("\nFontes: ", style="dim")
        t.append(", ".join(g.sources), style="#c678dd")
        if g.url:
            t.append("   (o = abrir)", style="dim")
        box.update(t)

    # ── eventos
    @on(DataTable.RowHighlighted)
    def _hl(self, ev: DataTable.RowHighlighted) -> None:
        if ev.row_key and ev.row_key.value is not None:
            self.show_detail(int(ev.row_key.value))

    @on(SelectionList.SelectedChanged)
    def _plat(self) -> None:
        if self.search_results is None:
            self.render_table()

    @on(Input.Submitted, "#search")
    def _submit(self, ev: Input.Submitted) -> None:
        q = ev.value.strip()
        self.query_one("#table").focus()
        if q:
            self.run_worker(self._search(q), exclusive=True, group="search")
        else:
            self.action_clear()

    async def _search(self, q: str) -> None:
        self.query_one("#table", DataTable).border_title = f"Buscando “{q}”…"
        c = self.client
        if not self.extra_years_loaded:
            self.extra_years_loaded = True
            try:
                more = await asyncio.gather(*(fetch_wiki(c, y) for y in
                                              (self.today.year - 1, self.today.year + 1)))
                self.pool = merge(self.pool, *more)
            except Exception:  # noqa: BLE001
                pass
        toks = q.lower().split()
        local = [g for g in self.pool if all(tk in g.name.lower() for tk in toks)]
        online = await asyncio.gather(steam_search(c, q), rawg_search(c, q), return_exceptions=True)
        online = [o for o in online if not isinstance(o, Exception)]
        res = merge(local, *online)
        res = [g for g in res if all(tk in g.name.lower() for tk in toks)]
        res.sort(key=lambda g: (not norm(g.name).startswith(norm(q)), -(g.d.toordinal() if g.d else 0)))
        self.search_results = res
        self.render_table()

    # ── ações
    def action_search(self) -> None:
        s = self.query_one("#search", Input)
        s.styles.display = "block"
        s.value = ""
        s.focus()

    def action_clear(self) -> None:
        self.search_results = None
        s = self.query_one("#search", Input)
        s.styles.display = "none"
        s.value = ""
        self.query_one("#table").focus()
        self.render_table()

    def action_refresh(self) -> None:
        self.load(force=True)

    def action_window(self) -> None:
        self.win_i = (self.win_i + 1) % len(WINDOWS)
        if self.search_results is None:
            self.render_table()

    def action_curated(self) -> None:
        self.curated_only = not self.curated_only
        if self.search_results is None:
            self.render_table()

    def action_open(self) -> None:
        t = self.query_one("#table", DataTable)
        if self.view and t.cursor_row is not None and t.cursor_row < len(self.view):
            g = self.view[t.cursor_row]
            webbrowser.open(g.url or f"https://www.google.com/search?q={g.name}+game")

    async def on_unmount(self) -> None:
        if self.client:
            await self.client.aclose()


def main() -> None:
    GameCal().run()


if __name__ == "__main__":
    main()
