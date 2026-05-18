"""Constantes compartilhadas da implementação distribuída de Risk."""

from __future__ import annotations

from dataclasses import dataclass


PLAYER_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (205, 64, 64),
    "blue": (82, 132, 220),
    "green": (84, 170, 94),
    "yellow": (210, 190, 72),
    "black": (70, 70, 78),
}

PLAYER_COLOR_LABELS: dict[str, str] = {
    "red": "Vermelho",
    "blue": "Azul",
    "green": "Verde",
    "yellow": "Amarelo",
    "black": "Preto",
}

CONTINENT_BONUSES: dict[str, int] = {
    "north_america": 5,
    "south_america": 2,
    "europe": 5,
    "africa": 3,
    "asia": 7,
    "australia": 2,
}

CONTINENT_LABELS: dict[str, str] = {
    "north_america": "América do Norte",
    "south_america": "América do Sul",
    "europe": "Europa",
    "africa": "África",
    "asia": "Ásia",
    "australia": "Oceania",
}

CONTINENT_COLORS: dict[str, tuple[int, int, int]] = {
    "north_america": (219, 221, 54),
    "south_america": (216, 91, 54),
    "europe": (78, 186, 216),
    "africa": (173, 132, 18),
    "asia": (134, 212, 126),
    "australia": (172, 58, 184),
}

TERRITORY_SHORT_LABELS: dict[str, str] = {
    "northwest_territory": "T. Noroeste",
    "western_united_states": "Oeste EUA",
    "eastern_united_states": "Leste EUA",
    "central_america": "A. Central",
    "great_britain": "Grã-Bret.",
    "northern_europe": "N. Europa",
    "western_europe": "O. Europa",
    "southern_europe": "S. Europa",
    "north_africa": "N. África",
    "east_africa": "A. Oriental",
    "south_africa": "A. do Sul",
    "middle_east": "Or. Médio",
    "new_guinea": "N. Guiné",
    "western_australia": "O. Austrália",
    "eastern_australia": "L. Austrália",
}

CARD_SYMBOLS = ("infantry", "cavalry", "artillery")
TRADE_VALUES = (4, 6, 8, 10, 12, 15)
MIN_PLAYERS = 2
MAX_PLAYERS = 2
DEFAULT_PORT = 5000
SNAPSHOT_POLL_MS = 200
TURN_TIMEOUT_SECONDS = 10.0
BOARD_ASSET_PATH = "risk_dist/assets/board.png"
MAP_ASSET_PATH = "risk_dist/assets/world_map.tmx"


MISSION_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "id": "asia_africa",
        "label": "Conquiste a Ásia e a África.",
        "kind": "continents_exact",
        "continents": ["asia", "africa"],
    },
    {
        "id": "asia_south_america",
        "label": "Conquiste a Ásia e a América do Sul.",
        "kind": "continents_exact",
        "continents": ["asia", "south_america"],
    },
    {
        "id": "north_america_africa",
        "label": "Conquiste a América do Norte e a África.",
        "kind": "continents_exact",
        "continents": ["north_america", "africa"],
    },
    {
        "id": "north_america_australia",
        "label": "Conquiste a América do Norte e a Oceania.",
        "kind": "continents_exact",
        "continents": ["north_america", "australia"],
    },
    {
        "id": "europe_south_america_plus_one",
        "label": "Conquiste a Europa, a América do Sul e mais um continente.",
        "kind": "continents_plus_one",
        "base": ["europe", "south_america"],
    },
    {
        "id": "europe_australia_plus_one",
        "label": "Conquiste a Europa, a Oceania e mais um continente.",
        "kind": "continents_plus_one",
        "base": ["europe", "australia"],
    },
    {
        "id": "occupy_24",
        "label": "Ocupe 24 territórios.",
        "kind": "territory_count",
        "count": 24,
    },
    {
        "id": "occupy_18_with_2",
        "label": "Ocupe 18 territórios com pelo menos 2 tropas em cada um.",
        "kind": "territory_troops",
        "count": 18,
        "min_troops": 2,
    },
)


@dataclass(frozen=True)
class SymbolBreakdown:
    infantry: int
    cavalry: int
    artillery: int


def troop_breakdown(total_troops: int) -> SymbolBreakdown:
    """Converte um total de tropas em símbolos de infantaria/cavalaria/artilharia."""
    artillery = total_troops // 10
    remainder = total_troops % 10
    cavalry = remainder // 5
    infantry = remainder % 5
    return SymbolBreakdown(
        infantry=infantry,
        cavalry=cavalry,
        artillery=artillery,
    )


def trade_value_for_index(trade_index: int) -> int:
    """Retorna o valor progressivo de reforço para a N-ésima troca global."""
    if trade_index < len(TRADE_VALUES):
        return TRADE_VALUES[trade_index]
    return TRADE_VALUES[-1] + (trade_index - len(TRADE_VALUES) + 1) * 5
