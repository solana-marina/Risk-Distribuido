"""Funções de regra compartilhadas entre os testes e o servidor autoritativo."""

from __future__ import annotations

from collections import Counter, deque
from itertools import combinations
from typing import Iterable

from .board import BoardDefinition
from .constants import CONTINENT_BONUSES, MISSION_DEFINITIONS, trade_value_for_index


def build_territory_cards(board: BoardDefinition) -> list[dict[str, object]]:
    """Monta as 42 cartas clássicas de território e os 2 curingas."""
    cards: list[dict[str, object]] = []
    symbols = ("infantry", "cavalry", "artillery")
    for index, territory_id in enumerate(board.territories_in_order):
        cards.append(
            {
                "id": f"territory_{territory_id}",
                "territory": territory_id,
                "symbol": symbols[index % len(symbols)],
                "kind": "territory",
            }
        )
    cards.append({"id": "wild_1", "territory": None, "symbol": "wild", "kind": "wild"})
    cards.append({"id": "wild_2", "territory": None, "symbol": "wild", "kind": "wild"})
    return cards


def card_lookup(cards: Iterable[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(card["id"]): card for card in cards}


def is_valid_trade_set(cards: list[dict[str, object]]) -> bool:
    """Valida as combinações padrão de troca de cartas do Risk."""
    if len(cards) != 3:
        return False
    symbols = [str(card["symbol"]) for card in cards]
    wild_count = symbols.count("wild")
    non_wild = [symbol for symbol in symbols if symbol != "wild"]
    unique_non_wild = set(non_wild)
    if wild_count == 3:
        return True
    if wild_count == 2:
        return True
    if wild_count == 1:
        return len(unique_non_wild) in (1, 2)
    return len(unique_non_wild) == 1 or len(unique_non_wild) == 3


def enumerate_trade_sets(cards: list[dict[str, object]]) -> list[list[str]]:
    """Retorna todos os conjuntos válidos de 3 cartas usando os IDs das cartas."""
    results: list[list[str]] = []
    for combo in combinations(cards, 3):
        if is_valid_trade_set(list(combo)):
            results.append([str(card["id"]) for card in combo])
    return results


def owned_continents(
    player_id: str,
    territories: dict[str, dict[str, object]],
    board: BoardDefinition,
) -> list[str]:
    continents = board.continents()
    result: list[str] = []
    for continent, territory_ids in continents.items():
        if all(territories[territory_id]["owner"] == player_id for territory_id in territory_ids):
            result.append(continent)
    return result


def reinforcement_total(
    player_id: str,
    territories: dict[str, dict[str, object]],
    board: BoardDefinition,
) -> dict[str, object]:
    territory_count = sum(1 for state in territories.values() if state["owner"] == player_id)
    base = max(3, territory_count // 3)
    continents = owned_continents(player_id, territories, board)
    bonus = sum(CONTINENT_BONUSES[continent] for continent in continents)
    return {
        "territories": territory_count,
        "base": base,
        "continents": continents,
        "continent_bonus": bonus,
        "total": base + bonus,
    }


def mission_by_id(mission_id: str) -> dict[str, object]:
    for mission in MISSION_DEFINITIONS:
        if mission["id"] == mission_id:
            return dict(mission)
    raise KeyError(mission_id)


def mission_completed(
    player_id: str,
    mission: dict[str, object],
    territories: dict[str, dict[str, object]],
    board: BoardDefinition,
) -> bool:
    owned = {territory_id for territory_id, state in territories.items() if state["owner"] == player_id}
    owned_continent_ids = set(owned_continents(player_id, territories, board))
    kind = mission["kind"]
    if kind == "continents_exact":
        return set(mission["continents"]) <= owned_continent_ids
    if kind == "continents_plus_one":
        base = set(mission["base"])
        return base <= owned_continent_ids and len(owned_continent_ids - base) >= 1
    if kind == "territory_count":
        return len(owned) >= int(mission["count"])
    if kind == "territory_troops":
        count = sum(
            1
            for territory_id in owned
            if int(territories[territory_id]["troops"]) >= int(mission["min_troops"])
        )
        return count >= int(mission["count"])
    raise ValueError(f"Tipo de missão não suportado: {kind}")


def connected_owned_path(
    player_id: str,
    source_id: str,
    target_id: str,
    territories: dict[str, dict[str, object]],
    board: BoardDefinition,
) -> bool:
    if source_id == target_id:
        return True
    queue: deque[str] = deque([source_id])
    seen = {source_id}
    while queue:
        current = queue.popleft()
        for neighbor in board.adjacency(current):
            if neighbor in seen:
                continue
            if territories[neighbor]["owner"] != player_id:
                continue
            if neighbor == target_id:
                return True
            seen.add(neighbor)
            queue.append(neighbor)
    return False


def resolve_battle(
    attacker_rolls: list[int],
    defender_rolls: list[int],
) -> dict[str, object]:
    attacker_sorted = sorted(attacker_rolls, reverse=True)
    defender_sorted = sorted(defender_rolls, reverse=True)
    attacker_losses = 0
    defender_losses = 0
    for attack_roll, defend_roll in zip(attacker_sorted, defender_sorted):
        if attack_roll > defend_roll:
            defender_losses += 1
        else:
            attacker_losses += 1
    return {
        "attacker_rolls": attacker_sorted,
        "defender_rolls": defender_sorted,
        "attacker_losses": attacker_losses,
        "defender_losses": defender_losses,
    }


def first_valid_trade(cards: list[dict[str, object]]) -> list[str] | None:
    sets = enumerate_trade_sets(cards)
    return sets[0] if sets else None


def player_must_trade(hand_size: int) -> bool:
    return hand_size >= 5


def trade_result_value(global_trade_count: int) -> int:
    return trade_value_for_index(global_trade_count)


def symbol_histogram(cards: Iterable[dict[str, object]]) -> Counter[str]:
    return Counter(str(card["symbol"]) for card in cards)
