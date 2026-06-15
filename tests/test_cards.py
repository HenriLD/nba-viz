"""Entity-card tokenizer + figure scraping (pure, no DB)."""
from app.cards import _figure_texts, _tokens


def test_strip_singular_possessive():
    assert _tokens("Jokic's points in wins") == ["jokic", "points", "in", "wins"]


def test_strip_plural_possessive():
    assert _tokens("the Lakers' defense") == ["the", "lakers", "defense"]


def test_keeps_name_internal_apostrophe():
    assert _tokens("D'Angelo Russell assists") == ["d'angelo", "russell", "assists"]


def test_folds_diacritics():
    assert _tokens("Dončić scoring") == ["doncic", "scoring"]


def test_splits_on_punctuation():
    # '.' is kept in tokens (harmless — no entity key contains it), commas split.
    assert _tokens("Curry vs. Tatum, shot chart") == [
        "curry", "vs.", "tatum", "shot", "chart"]


def test_figure_texts_pulls_title_subtitle_and_data():
    # title/subtitle come back first, then names plotted in the data.
    fig = {
        "layout": {"title": {"text": "<b>Top scorers</b>",
                             "subtitle": {"text": "2025-26 season"}}},
        "data": [
            {"type": "bar", "x": ["Shai Gilgeous-Alexander", "Luka Doncic"],
             "y": [33, 31]},
            {"type": "scatter", "name": "Nikola Jokic", "x": [1], "y": [2]},
        ],
    }
    title_texts, data_texts = _figure_texts(fig)
    assert title_texts == ["Top scorers", "2025-26 season"]   # <b> stripped
    assert "Shai Gilgeous-Alexander" in data_texts
    assert "Luka Doncic" in data_texts
    assert "Nikola Jokic" in data_texts


def test_figure_texts_skips_numeric_and_bdata_axes():
    # numeric axis values (and base64 'bdata' encodings to_json may emit) carry
    # no names and must not crash the scan.
    fig = {"layout": {}, "data": [
        {"type": "scatter", "x": {"bdata": "AAAA", "dtype": "f8"}, "y": [1, 2, 3]},
    ]}
    title_texts, data_texts = _figure_texts(fig)
    assert title_texts == [] and data_texts == []


def test_figure_texts_reads_table_cells():
    fig = {"layout": {}, "data": [
        {"type": "table",
         "header": {"values": ["<b>Player</b>", "<b>PTS</b>"]},
         "cells": {"values": [["LeBron James", "Stephen Curry"], [27, 25]]}},
    ]}
    _, data_texts = _figure_texts(fig)
    assert "LeBron James" in data_texts and "Stephen Curry" in data_texts
    assert "Player" in data_texts   # header tags stripped
