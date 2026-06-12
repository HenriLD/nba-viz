"""Fuzzy entity resolution: the model sends 'steph curry', we find the row.

Small models are unreliable with exact names/IDs, so resolution always happens
server-side against the players/teams tables.
"""
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import fuzz, process

from core.db import query_df


class EntityNotFound(ValueError):
    pass


@dataclass
class Player:
    player_id: int
    full_name: str


@dataclass
class Team:
    team_id: int
    full_name: str
    abbreviation: str


@lru_cache(maxsize=1)
def _player_index() -> dict[str, Player]:
    df = query_df("SELECT player_id, full_name FROM players")
    return {r.full_name.lower(): Player(r.player_id, r.full_name)
            for r in df.itertuples()}


@lru_cache(maxsize=1)
def _team_index() -> dict[str, Team]:
    df = query_df("SELECT team_id, full_name, abbreviation, nickname, city FROM teams")
    idx: dict[str, Team] = {}
    for r in df.itertuples():
        t = Team(r.team_id, r.full_name, r.abbreviation)
        for key in (r.full_name, r.nickname, r.city, r.abbreviation):
            if key:
                idx[key.lower()] = t
    return idx


def _resolve(name: str, index: dict, kind: str):
    key = name.strip().lower()
    if key in index:
        return index[key]
    match = process.extractOne(key, index.keys(), scorer=fuzz.WRatio, score_cutoff=80)
    if match:
        return index[match[0]]
    close = process.extract(key, index.keys(), scorer=fuzz.WRatio, limit=3)
    suggestions = ", ".join(index[c[0]].full_name for c in close)
    raise EntityNotFound(
        f"No {kind} matching '{name}'. Did you mean: {suggestions}?")


def resolve_player(name: str) -> Player:
    return _resolve(name, _player_index(), "player")


def resolve_team(name: str) -> Team:
    return _resolve(name, _team_index(), "team")


def clear_cache() -> None:
    _player_index.cache_clear()
    _team_index.cache_clear()
