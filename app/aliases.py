"""Curated player nickname -> canonical name map.

The NBA API does not carry colloquial nicknames (SGA, CP3, Wemby, Greek
Freak...), so fuzzy matching alone can't resolve them — an acronym like "SGA"
has no string overlap with "Shai Gilgeous-Alexander". This hand-maintained map
is consulted before fuzzy resolution; values are real names that then resolve
through the normal (diacritic-folded, active-biased) path.

Keys are matched case/space/diacritic-insensitively. Extend freely.
"""

# alias -> canonical name (as a substring sufficient for resolution)
_RAW = {
    # Guards
    "sga": "shai gilgeous-alexander",
    "shai": "shai gilgeous-alexander",
    "cp3": "chris paul",
    "dame": "damian lillard",
    "dame dolla": "damian lillard",
    "steph": "stephen curry",
    "chef curry": "stephen curry",
    "klay": "klay thompson",
    "russ": "russell westbrook",
    "brodie": "russell westbrook",
    "ja": "ja morant",
    "trae": "trae young",
    "ice trae": "trae young",
    "dlo": "d'angelo russell",
    "book": "devin booker",
    "cade": "cade cunningham",
    "tyrese hali": "tyrese haliburton",
    "hali": "tyrese haliburton",
    "maxey": "tyrese maxey",
    # Wings / forwards
    "kd": "kevin durant",
    "the slim reaper": "kevin durant",
    "pg": "paul george",
    "pg13": "paul george",
    "kawhi": "kawhi leonard",
    "the klaw": "kawhi leonard",
    "jt": "jayson tatum",
    "tatum": "jayson tatum",
    "jb": "jaylen brown",
    "bron": "lebron james",
    "king james": "lebron james",
    "lebron": "lebron james",
    "the king": "lebron james",
    "zion": "zion williamson",
    "paolo": "paolo banchero",
    "scottie": "scottie barnes",
    "mpj": "michael porter jr",
    "og": "og anunoby",
    "kuz": "kyle kuzma",
    # Bigs
    "wemby": "victor wembanyama",
    "the alien": "victor wembanyama",
    "greek freak": "giannis antetokounmpo",
    "the greek freak": "giannis antetokounmpo",
    "giannis": "giannis antetokounmpo",
    "joker": "nikola jokic",
    "the joker": "nikola jokic",
    "jojo": "joel embiid",
    "the process": "joel embiid",
    "ad": "anthony davis",
    "the brow": "anthony davis",
    "kat": "karl-anthony towns",
    "bam": "bam adebayo",
    "chet": "chet holmgren",
    "the unicorn": "kristaps porzingis",
    "zubac": "ivica zubac",
    # Misc stars
    "spida": "donovan mitchell",
    "the beard": "james harden",
    "luka": "luka doncic",
    "the don": "luka doncic",
}


def _fold_key(s: str) -> str:
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Pre-folded so lookups are O(1) against the resolver's folded keys.
PLAYER_ALIASES = {_fold_key(k): v for k, v in _RAW.items()}


# Colloquial team short-forms the NBA data doesn't carry (it stores only the
# official city / nickname / abbreviation). alias -> 3-letter abbreviation.
_TEAM_RAW = {
    "sixers": "PHI", "philly": "PHI",
    "wolves": "MIN", "twolves": "MIN", "t-wolves": "MIN", "t wolves": "MIN",
    "cavs": "CLE",
    "mavs": "DAL",
    "blazers": "POR",
    "dubs": "GSW", "golden state": "GSW",
    "grizz": "MEM",
    "pels": "NOP", "nola": "NOP",
    "nugs": "DEN",
    "clips": "LAC",
    "wizz": "WAS",
}

TEAM_ALIASES = {_fold_key(k): v for k, v in _TEAM_RAW.items()}
