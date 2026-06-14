"""Entity side-cards: detect players/teams named in a question and build a
small bio+stats payload for each — with NO LLM call.

The frontend shows these as boxes flanking the chart (players left, teams
right), each flippable through the entities mentioned. Detection is a
heuristic exact-match scan of the message against the player/team name
indexes (full names, surnames, curated aliases, team names/abbrs); stats and
bio are derived entirely from the existing database. Headshots and team logos
load client-side from the public NBA CDN.

True bio (height/age/draft) isn't stored, so "bio" here is position (from the
defense-tracking table when available), current team, season span and
active/retired status — the NBA.com link covers the rest.
"""
import re
from functools import lru_cache

from app.aliases import PLAYER_ALIASES
from app.entities import _fold, _team_index
from core.db import query_df

# CDN templates (verified to resolve): a transparent-bg headshot PNG and the
# primary team logo SVG, both keyed by the same ids we already store.
HEADSHOT = "https://cdn.nba.com/headshots/nba/latest/1040x760/{id}.png"
TEAM_LOGO = "https://cdn.nba.com/logos/nba/{id}/global/L/logo.svg"
PLAYER_URL = "https://www.nba.com/player/{id}"
TEAM_URL = "https://www.nba.com/team/{id}"

MAX_PER_SIDE = 5  # cap boxes per side so a stat-stuffed prompt can't blow up

# Surnames that are also common English words: only match these as a *bare*
# surname token via the full name / first+last instead, to avoid "young
# players" -> Trae Young. (Full-name and alias keys still match them fine.)
_COMMON_WORD_SURNAMES = {
    "young", "green", "white", "brown", "love", "smart", "king", "west",
    "day", "rich", "wood", "banks", "english", "may", "price",
}
# Team nicknames that collide with this app's own vocabulary: skip the team
# match when the next token forms a known non-team phrase (e.g. "heat map").
_NICK_NEXT_GUARD = {"heat": {"map", "maps", "check", "index", "wave"}}


# --------------------------------------------------------------- name index

@lru_cache(maxsize=1)
def _player_games() -> dict[int, int]:
    """player_id -> games in the DB, a cheap prominence proxy for picking the
    right player when a surname is shared (active + most games wins)."""
    df = query_df("SELECT player_id, count(*) AS g FROM player_game_logs "
                  "GROUP BY player_id")
    return {int(r.player_id): int(r.g) for r in df.itertuples()}


@lru_cache(maxsize=1)
def _name_index() -> dict[str, tuple[str, int]]:
    """folded name token(s) -> ('player'|'team', id). Longer/eponymous keys are
    inserted so that more specific matches win; teams are added last so a word
    that is both a surname and a team name resolves to the team."""
    games = _player_games()
    df = query_df("SELECT player_id, full_name, is_active FROM players")

    # Resolve a surname to the most prominent player carrying it.
    by_surname: dict[str, list[tuple[int, bool]]] = {}
    idx: dict[str, tuple[str, int]] = {}
    for r in df.itertuples():
        pid = int(r.player_id)
        idx[_fold(r.full_name)] = ("player", pid)
        parts = _fold(r.full_name).split()
        if parts:
            by_surname.setdefault(parts[-1], []).append((pid, bool(r.is_active)))

    for surname, cands in by_surname.items():
        if surname in _COMMON_WORD_SURNAMES:
            continue
        # Prefer active players, then those with the most games on record.
        best = max(cands, key=lambda c: (c[1], games.get(c[0], 0)))
        idx.setdefault(surname, ("player", best[0]))

    # Curated nicknames -> whichever player their canonical name resolves to.
    for alias, canonical in PLAYER_ALIASES.items():
        hit = idx.get(_fold(canonical))
        if hit:
            idx[alias] = hit

    # Teams last (override any surname collision like a city/nickname word).
    for key, team in _team_index().items():
        idx[key] = ("team", team.team_id)
    return idx


def _tokens(message: str) -> list[str]:
    folded = _fold(message)
    return [t for t in re.split(r"[^a-z0-9.'-]+", folded) if t]


def extract_entities(message: str) -> tuple[list[int], list[int]]:
    """Return (player_ids, team_ids) named in the message, in order of first
    appearance, de-duplicated. Greedy longest-match (3->1 grams) so a full name
    isn't also counted as its surname, and matched tokens aren't reused."""
    idx = _name_index()
    toks = _tokens(message)
    players: list[int] = []
    teams: list[int] = []
    seen: set[tuple[str, int]] = set()
    i = 0
    while i < len(toks):
        matched = False
        for n in (3, 2, 1):
            if i + n > len(toks):
                continue
            gram = " ".join(toks[i:i + n])
            hit = idx.get(gram)
            if not hit:
                continue
            # Guard team nicknames that double as app vocabulary ("heat map").
            if n == 1 and hit[0] == "team":
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if nxt in _NICK_NEXT_GUARD.get(gram, set()):
                    continue
            if hit not in seen:
                seen.add(hit)
                (players if hit[0] == "player" else teams).append(hit[1])
            i += n
            matched = True
            break
        if not matched:
            i += 1
    return players[:MAX_PER_SIDE], teams[:MAX_PER_SIDE]


# --------------------------------------------------------------- formatting

def _f1(x) -> str | None:
    return f"{float(x):.1f}" if x is not None else None


def _signed1(x) -> str | None:
    return f"{float(x):+.1f}" if x is not None else None


def _pct(x) -> str | None:
    return f"{float(x) * 100:.1f}%" if x is not None else None


def _first(df, col, default=None):
    return df[col].iloc[0] if not df.empty and df[col].iloc[0] is not None else default


# --------------------------------------------------------------- card builders

@lru_cache(maxsize=256)
def player_card(pid: int) -> dict | None:
    info = query_df("SELECT full_name, is_active FROM players WHERE player_id = :id",
                    {"id": pid})
    if info.empty:
        return None
    name = info["full_name"].iloc[0]
    active = bool(info["is_active"].iloc[0])

    avg = query_df(
        "SELECT season, gp, pts, reb, ast, fg_pct, fg3_pct "
        "FROM player_season_averages WHERE player_id = :id "
        "ORDER BY season DESC LIMIT 1", {"id": pid})
    team = _first(query_df(
        "SELECT team_abbreviation FROM player_game_logs WHERE player_id = :id "
        "ORDER BY game_date DESC LIMIT 1", {"id": pid}), "team_abbreviation")
    pos = _first(query_df(
        "SELECT player_position FROM defense_tracking WHERE player_id = :id "
        "ORDER BY season DESC LIMIT 1", {"id": pid}), "player_position")

    bio = " · ".join(p for p in (pos, team, "Active" if active else "Retired") if p)
    stats, caption = [], "no recent games"
    if not avg.empty:
        r = avg.iloc[0]
        caption = f"{r['season']} averages"
        stats = [s for s in (
            {"label": "PPG", "value": _f1(r["pts"])},
            {"label": "RPG", "value": _f1(r["reb"])},
            {"label": "APG", "value": _f1(r["ast"])},
            {"label": "FG%", "value": _pct(r["fg_pct"])},
            {"label": "3P%", "value": _pct(r["fg3_pct"])},
            {"label": "GP", "value": str(int(r["gp"])) if r["gp"] is not None else None},
        ) if s["value"] is not None]

    return {"kind": "player", "id": pid, "name": name,
            "image": HEADSHOT.format(id=pid), "href": PLAYER_URL.format(id=pid),
            "bio": bio, "caption": caption, "stats": stats}


@lru_cache(maxsize=64)
def team_card(tid: int) -> dict | None:
    info = query_df("SELECT full_name, abbreviation FROM teams WHERE team_id = :id",
                    {"id": tid})
    if info.empty:
        return None
    name = info["full_name"].iloc[0]
    abbr = info["abbreviation"].iloc[0]

    season_row = query_df(
        "SELECT season, gp, wins, losses, pts_pg, opp_pts_pg, net_pg, "
        "fg3a_pg, fg3_pct FROM v_team_season WHERE team = :abbr "
        "ORDER BY season DESC LIMIT 1", {"abbr": abbr})
    standing = query_df(
        "SELECT conference, wins, losses, playoff_rank FROM standings "
        "WHERE team_id = :id ORDER BY season DESC LIMIT 1", {"id": tid})

    bio_parts, stats, caption = [], [], "no recent games"
    if not standing.empty:
        s = standing.iloc[0]
        conf = s["conference"]
        rec = f"{int(s['wins'])}–{int(s['losses'])}" if s["wins"] is not None else None
        rank = f"#{int(s['playoff_rank'])}" if s["playoff_rank"] is not None else None
        bio_parts = [p for p in (conf, rec, rank) if p]
    if not season_row.empty:
        r = season_row.iloc[0]
        caption = f"{r['season']} season"
        stats = [s for s in (
            {"label": "PPG", "value": _f1(r["pts_pg"])},
            {"label": "OPP", "value": _f1(r["opp_pts_pg"])},
            {"label": "NET", "value": _signed1(r["net_pg"])},
            {"label": "3PA", "value": _f1(r["fg3a_pg"])},
            {"label": "3P%", "value": _pct(r["fg3_pct"])},
            {"label": "GP", "value": str(int(r["gp"])) if r["gp"] is not None else None},
        ) if s["value"] is not None]

    return {"kind": "team", "id": tid, "name": name,
            "image": TEAM_LOGO.format(id=tid), "href": TEAM_URL.format(id=tid),
            "bio": " · ".join(bio_parts), "caption": caption, "stats": stats}


def cards_for(message: str) -> dict:
    """{"players": [...], "teams": [...]} for the entities named in `message`.
    Best-effort: a failure building any single card is skipped, never raised,
    so side-cards can't break the chat response."""
    player_ids, team_ids = extract_entities(message)
    players, teams = [], []
    for pid in player_ids:
        try:
            c = player_card(pid)
            if c:
                players.append(c)
        except Exception:  # noqa: BLE001 — cards are decorative, never fatal
            pass
    for tid in team_ids:
        try:
            c = team_card(tid)
            if c:
                teams.append(c)
        except Exception:  # noqa: BLE001
            pass
    return {"players": players, "teams": teams}


def clear_cache() -> None:
    _player_games.cache_clear()
    _name_index.cache_clear()
    player_card.cache_clear()
    team_card.cache_clear()
