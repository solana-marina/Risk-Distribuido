"""Estado autoritativo do jogo e execução das regras."""

from __future__ import annotations

import random
import threading
import time
import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from risk_dist.shared.board import BoardDefinition, load_board
from risk_dist.shared.constants import (
    MAX_PLAYERS,
    MIN_PLAYERS,
    MISSION_DEFINITIONS,
    PLAYER_COLOR_LABELS,
    TURN_TIMEOUT_SECONDS,
)
from risk_dist.shared.rules import (
    build_territory_cards,
    card_lookup,
    connected_owned_path,
    enumerate_trade_sets,
    first_valid_trade,
    is_valid_trade_set,
    mission_by_id,
    mission_completed,
    owned_continents,
    player_must_trade,
    reinforcement_total,
    resolve_battle,
    trade_result_value,
)


@dataclass
class PlayerState:
    player_id: str
    name: str
    color: str | None = None
    ready: bool = False
    mission: dict[str, object] | None = None
    hand: list[dict[str, object]] = field(default_factory=list)
    setup_troops_left: int = 0
    reinforcements_to_place: int = 0
    alive: bool = True
    last_seen: float = field(default_factory=time.time)


class RiskGame:
    """Estado de uma partida única para dois jogadores em rede local."""

    def __init__(self, board: BoardDefinition | None = None, seed: int | None = None) -> None:
        self.board = board or load_board()
        self._rng = random.Random(seed)
        self._lock = threading.RLock()
        self.version = 0
        self.players: dict[str, PlayerState] = {}
        self.territories = {
            territory_id: {"owner": None, "troops": 0}
            for territory_id in self.board.territories_in_order
        }
        self.phase = "lobby"
        self.current_player_id: str | None = None
        self.first_player_id: str | None = None
        self.pending_prompt: dict[str, object] | None = None
        self.pending_battle: dict[str, object] | None = None
        self.log_entries: list[str] = []
        self.last_battle: dict[str, object] | None = None
        self.status_message = "Aguardando jogadores."
        self.winner_id: str | None = None
        self.global_trade_count = 0
        self.turn_conquest_happened = False
        self.turn_card_awarded = False
        self.fortify_used = False
        self.draw_deck: list[dict[str, object]] = []
        self.discard_pile: list[dict[str, object]] = []
        self._card_catalog = card_lookup(build_territory_cards(self.board))

    def join_game(self, name: str) -> dict[str, object]:
        with self._lock:
            self._check_disconnects()
            if self.phase != "lobby" and len(self.players) >= MAX_PLAYERS:
                return {"ok": False, "error": "A partida já está em andamento."}
            if len(self.players) >= MAX_PLAYERS:
                return {"ok": False, "error": "A sala já está cheia."}
            player_id = str(uuid.uuid4())
            self.players[player_id] = PlayerState(player_id=player_id, name=name[:24] or "Jogador")
            self._log(f"{name} entrou na sala.")
            self._set_status("Escolha uma cor e marque-se como pronto.")
            self._bump_version()
            return {"ok": True, "player_id": player_id}

    def leave_game(self, player_id: str) -> dict[str, object]:
        with self._lock:
            player = self.players.get(player_id)
            if not player:
                return {"ok": False, "error": "Jogador desconhecido."}
            if self.phase == "lobby":
                self._log(f"{player.name} saiu da sala.")
                del self.players[player_id]
                self._set_status("Aguardando jogadores.")
                self._bump_version()
                return {"ok": True}
            self._declare_winner(
                next((pid for pid in self.players if pid != player_id), None),
                f"{player.name} desconectou.",
            )
            self._bump_version()
            return {"ok": True}

    def choose_color(self, player_id: str, color: str) -> dict[str, object]:
        with self._lock:
            self._touch(player_id)
            if self.phase != "lobby":
                return {"ok": False, "error": "A escolha de cor está bloqueada."}
            player = self.players[player_id]
            if player.color == color:
                return {"ok": True}
            if color not in self.available_colors():
                return {"ok": False, "error": "Essa cor não está disponível."}
            player.color = color
            self._log(f"{player.name} escolheu a cor {PLAYER_COLOR_LABELS.get(color, color)}.")
            self._maybe_start_game()
            self._bump_version()
            return {"ok": True}

    def ready(self, player_id: str) -> dict[str, object]:
        with self._lock:
            self._touch(player_id)
            if self.phase != "lobby":
                return {"ok": False, "error": "A partida já começou."}
            player = self.players[player_id]
            if not player.color:
                return {"ok": False, "error": "Escolha uma cor primeiro."}
            player.ready = True
            self._log(f"{player.name} está pronto.")
            self._maybe_start_game()
            self._bump_version()
            return {"ok": True}

    def get_snapshot(self, player_id: str, last_version: int | None) -> dict[str, object]:
        with self._lock:
            self._touch(player_id)
            self._check_disconnects()
            if player_id not in self.players:
                return {"updated": True, "version": self.version, "snapshot": {"error": "Jogador desconhecido."}}
            if last_version == self.version:
                return {"updated": False, "version": self.version, "snapshot": None}
            return {
                "updated": True,
                "version": self.version,
                "snapshot": self._build_snapshot(player_id),
            }

    def submit_action(self, player_id: str, action: str, payload: dict[str, object] | None) -> dict[str, object]:
        with self._lock:
            self._touch(player_id)
            self._check_disconnects()
            handlers = {
                "place_setup_army": self._action_place_setup_army,
                "trade_cards": self._action_trade_cards,
                "place_reinforcements": self._action_place_reinforcements,
                "attack": self._action_attack,
                "defend": self._action_defend,
                "capture_move": self._action_capture_move,
                "fortify": self._action_fortify,
                "end_attack_phase": self._action_end_attack_phase,
                "end_turn": self._action_end_turn,
            }
            handler = handlers.get(action)
            if not handler:
                return {"ok": False, "error": f"Ação não suportada: {action}"}
            result = handler(player_id, payload or {})
            if result.get("ok"):
                self._bump_version()
            return result

    def available_colors(self) -> set[str]:
        taken = {player.color for player in self.players.values() if player.color}
        from risk_dist.shared.constants import PLAYER_COLORS

        return set(PLAYER_COLORS) - taken

    def _action_place_setup_army(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "setup":
            return {"ok": False, "error": "A preparação já terminou."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é a sua vez de posicionar tropas."}
        territory_id = str(payload.get("territory_id", ""))
        player = self.players[player_id]
        if player.setup_troops_left <= 0:
            return {"ok": False, "error": "Você não tem mais tropas de preparação."}
        if self.territories.get(territory_id, {}).get("owner") != player_id:
            return {"ok": False, "error": "Você só pode reforçar um território seu."}
        self.territories[territory_id]["troops"] += 1
        player.setup_troops_left -= 1
        self._log(
            f"{player.name} colocou 1 tropa inicial em {self.board.display_name(territory_id)} "
            f"({player.setup_troops_left} restantes)."
        )
        self._advance_setup_turn()
        return {"ok": True}

    def _action_trade_cards(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "reinforcement":
            return {"ok": False, "error": "Você só pode trocar cartas no início do seu turno."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        if self.pending_prompt is not None:
            return {"ok": False, "error": "Resolva primeiro a solicitação pendente."}
        player = self.players[player_id]
        card_ids = [str(card_id) for card_id in payload.get("card_ids", [])]
        selected = [card for card in player.hand if str(card["id"]) in card_ids]
        if len(selected) != 3 or len(card_ids) != 3:
            return {"ok": False, "error": "Selecione exatamente 3 cartas para trocar."}
        if not is_valid_trade_set(selected):
            return {"ok": False, "error": "Esse conjunto de cartas não é válido."}
        for card in selected:
            player.hand.remove(card)
            self.discard_pile.append(card)
        bonus = trade_result_value(self.global_trade_count)
        self.global_trade_count += 1
        territory_bonus = 0
        if any(
            card.get("territory") and self.territories[str(card["territory"])]["owner"] == player_id
            for card in selected
        ):
            territory_bonus = 2
        player.reinforcements_to_place += bonus + territory_bonus
        self._log(
            f"{player.name} trocou cartas por {bonus + territory_bonus} tropas "
            f"({bonus} da troca + {territory_bonus} de bônus territorial)."
        )
        return {"ok": True, "trade_value": bonus + territory_bonus}

    def _action_place_reinforcements(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "reinforcement":
            return {"ok": False, "error": "Esta não é a fase de reforços."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        player = self.players[player_id]
        trade_sets = enumerate_trade_sets(player.hand)
        if player_must_trade(len(player.hand)) and trade_sets:
            return {"ok": False, "error": "Você precisa trocar cartas antes de posicionar reforços."}
        count = int(payload.get("count", 1))
        territory_id = str(payload.get("territory_id", ""))
        if count < 1 or count > player.reinforcements_to_place:
            return {"ok": False, "error": "Quantidade de reforços inválida."}
        if self.territories.get(territory_id, {}).get("owner") != player_id:
            return {"ok": False, "error": "Você só pode reforçar um território seu."}
        self.territories[territory_id]["troops"] += count
        player.reinforcements_to_place -= count
        self._log(
            f"{player.name} colocou {count} tropa(s) de reforço em "
            f"{self.board.display_name(territory_id)}."
        )
        if player.reinforcements_to_place == 0:
            self.phase = "attack"
            self._set_status(f"{player.name} agora pode atacar ou encerrar a fase de ataque.")
            self._check_winner(player_id)
        return {"ok": True}

    def _action_attack(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "attack":
            return {"ok": False, "error": "Ataques não estão disponíveis neste momento."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        if self.pending_prompt is not None:
            return {"ok": False, "error": "Resolva primeiro a solicitação pendente."}
        from_id = str(payload.get("from"))
        to_id = str(payload.get("to"))
        dice = int(payload.get("dice", 0))
        if from_id not in self.territories or to_id not in self.territories:
            return {"ok": False, "error": "Território desconhecido."}
        if self.territories[from_id]["owner"] != player_id:
            return {"ok": False, "error": "Você precisa atacar a partir de um território seu."}
        defender_id = self.territories[to_id]["owner"]
        if defender_id in (None, player_id):
            return {"ok": False, "error": "Escolha um alvo inimigo."}
        if to_id not in self.board.adjacency(from_id):
            return {"ok": False, "error": "Esses territórios não são adjacentes."}
        max_attack = min(3, int(self.territories[from_id]["troops"]) - 1)
        if max_attack < 1:
            return {"ok": False, "error": "Você precisa de pelo menos 2 tropas para atacar."}
        if dice < 1 or dice > max_attack:
            return {"ok": False, "error": "Quantidade de dados de ataque inválida."}
        self.pending_battle = {
            "attacker_id": player_id,
            "defender_id": defender_id,
            "from": from_id,
            "to": to_id,
            "attack_dice": dice,
        }
        max_defense = min(2, int(self.territories[to_id]["troops"]))
        self.pending_prompt = {
            "target_player_id": defender_id,
            "type": "defend",
            "from": from_id,
            "to": to_id,
            "attack_dice": dice,
            "max_defense_dice": max_defense,
        }
        attacker_name = self.players[player_id].name
        defender_name = self.players[defender_id].name
        self._set_status(f"{attacker_name} está atacando. Aguardando a defesa de {defender_name}.")
        return {"ok": True}

    def _action_defend(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        prompt = self.pending_prompt
        if not prompt or prompt.get("type") != "defend":
            return {"ok": False, "error": "Não existe uma solicitação de defesa para resolver."}
        if player_id != prompt.get("target_player_id"):
            return {"ok": False, "error": "Essa solicitação de defesa pertence ao outro jogador."}
        if not self.pending_battle:
            return {"ok": False, "error": "Nenhuma batalha pendente foi encontrada."}
        defense_dice = int(payload.get("dice", 0))
        battle = self.pending_battle
        target_id = str(battle["to"])
        max_defense = min(2, int(self.territories[target_id]["troops"]))
        if defense_dice < 1 or defense_dice > max_defense:
            return {"ok": False, "error": "Quantidade de dados de defesa inválida."}
        attacker_rolls = [self._rng.randint(1, 6) for _ in range(int(battle["attack_dice"]))]
        defender_rolls = [self._rng.randint(1, 6) for _ in range(defense_dice)]
        result = resolve_battle(attacker_rolls, defender_rolls)
        from_id = str(battle["from"])
        self.territories[from_id]["troops"] -= int(result["attacker_losses"])
        self.territories[target_id]["troops"] -= int(result["defender_losses"])
        attacker = self.players[str(battle["attacker_id"])]
        defender = self.players[str(battle["defender_id"])]
        self.last_battle = {
            **result,
            "attacker": attacker.name,
            "defender": defender.name,
            "from": from_id,
            "to": target_id,
        }
        self._log(
            f"Batalha {self.board.display_name(from_id)} -> {self.board.display_name(target_id)}: "
            f"{attacker.name} {result['attacker_rolls']} contra {defender.name} {result['defender_rolls']}. "
            f"Perdas A:{result['attacker_losses']} D:{result['defender_losses']}."
        )
        self.pending_prompt = None
        self.pending_battle = None
        if int(self.territories[target_id]["troops"]) <= 0:
            self.territories[target_id]["owner"] = attacker.player_id
            self.territories[target_id]["troops"] = 0
            eliminated_player_id = (
                defender.player_id if not self._player_territories(defender.player_id) else None
            )
            if eliminated_player_id:
                attacker.hand.extend(defender.hand)
                defender.hand.clear()
                defender.alive = False
                self._log(f"{attacker.name} eliminou {defender.name} e recebeu suas cartas.")
            move_max = int(self.territories[from_id]["troops"]) - 1
            move_min = int(battle["attack_dice"])
            self.pending_prompt = {
                "target_player_id": attacker.player_id,
                "type": "capture_move",
                "from": from_id,
                "to": target_id,
                "min_troops": move_min,
                "max_troops": move_max,
                "eliminated_player_id": eliminated_player_id,
            }
            self.turn_conquest_happened = True
            self._set_status(f"{attacker.name} conquistou um território e precisa mover tropas.")
        else:
            self._set_status(f"{attacker.name} pode continuar atacando ou encerrar a fase.")
        return {"ok": True}

    def _action_capture_move(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        prompt = self.pending_prompt
        if not prompt or prompt.get("type") != "capture_move":
            return {"ok": False, "error": "Não existe movimentação de conquista para resolver."}
        if player_id != prompt.get("target_player_id"):
            return {"ok": False, "error": "Essa solicitação pertence ao outro jogador."}
        move_count = int(payload.get("count", 0))
        min_troops = int(prompt["min_troops"])
        max_troops = int(prompt["max_troops"])
        if move_count < min_troops or move_count > max_troops:
            return {"ok": False, "error": "Quantidade de tropas para conquista inválida."}
        from_id = str(prompt["from"])
        to_id = str(prompt["to"])
        self.territories[from_id]["troops"] -= move_count
        self.territories[to_id]["troops"] += move_count
        self.pending_prompt = None
        self._log(
            f"{self.players[player_id].name} moveu {move_count} tropa(s) para "
            f"{self.board.display_name(to_id)}."
        )
        self._check_winner(player_id)
        if self.phase != "game_over":
            self.phase = "attack"
            self._set_status(f"{self.players[player_id].name} pode continuar atacando.")
        return {"ok": True}

    def _action_end_attack_phase(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "attack":
            return {"ok": False, "error": "Esta não é a fase de ataque."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        if self.pending_prompt is not None:
            return {"ok": False, "error": "Resolva primeiro a solicitação pendente."}
        self.phase = "fortify"
        self._set_status(f"{self.players[player_id].name} pode fazer uma manobra ou encerrar o turno.")
        return {"ok": True}

    def _action_fortify(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase != "fortify":
            return {"ok": False, "error": "Esta não é a fase de manobra."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        if self.fortify_used:
            return {"ok": False, "error": "Você já fez a manobra deste turno."}
        from_id = str(payload.get("from"))
        to_id = str(payload.get("to"))
        count = int(payload.get("count", 0))
        if self.territories.get(from_id, {}).get("owner") != player_id or self.territories.get(to_id, {}).get("owner") != player_id:
            return {"ok": False, "error": "A manobra só pode ocorrer entre territórios seus."}
        if count < 1 or count >= int(self.territories[from_id]["troops"]):
            return {"ok": False, "error": "Deixe pelo menos 1 tropa no território de origem."}
        if not connected_owned_path(player_id, from_id, to_id, self.territories, self.board):
            return {"ok": False, "error": "Esses territórios não estão conectados pelos seus domínios."}
        self.territories[from_id]["troops"] -= count
        self.territories[to_id]["troops"] += count
        self.fortify_used = True
        self._log(
            f"{self.players[player_id].name} moveu {count} tropa(s) de "
            f"{self.board.display_name(from_id)} para {self.board.display_name(to_id)}."
        )
        return self._finish_turn(player_id)

    def _action_end_turn(self, player_id: str, payload: dict[str, object]) -> dict[str, object]:
        if self.phase not in {"attack", "fortify"}:
            return {"ok": False, "error": "Você não pode encerrar o turno agora."}
        if player_id != self.current_player_id:
            return {"ok": False, "error": "Não é o seu turno."}
        if self.pending_prompt is not None:
            return {"ok": False, "error": "Resolva primeiro a solicitação pendente."}
        return self._finish_turn(player_id)

    def _finish_turn(self, player_id: str) -> dict[str, object]:
        player = self.players[player_id]
        if self.turn_conquest_happened and not self.turn_card_awarded:
            card = self._draw_card()
            if card:
                player.hand.append(card)
                self.turn_card_awarded = True
                self._log(f"{player.name} recebeu uma carta de território.")
        next_player_id = next(pid for pid in self.players if pid != player_id)
        self._start_turn(next_player_id)
        return {"ok": True}

    def _touch(self, player_id: str) -> None:
        if player_id in self.players:
            self.players[player_id].last_seen = time.time()

    def _check_disconnects(self) -> None:
        if self.phase in {"lobby", "game_over"}:
            return
        stale = [
            player
            for player in self.players.values()
            if time.time() - player.last_seen > TURN_TIMEOUT_SECONDS
        ]
        if not stale:
            return
        disconnected = stale[0]
        winner_id = next((pid for pid in self.players if pid != disconnected.player_id), None)
        self._declare_winner(winner_id, f"{disconnected.name} excedeu o tempo limite de conexão.")
        self._bump_version()

    def _maybe_start_game(self) -> None:
        if len(self.players) < MIN_PLAYERS:
            return
        players = list(self.players.values())
        if not all(player.ready and player.color for player in players):
            return
        self._initialize_match()

    def _initialize_match(self) -> None:
        player_ids = list(self.players)
        self._rng.shuffle(player_ids)
        mission_pool = [dict(mission) for mission in MISSION_DEFINITIONS]
        self._rng.shuffle(mission_pool)
        for player_id, mission in zip(player_ids, mission_pool, strict=False):
            self.players[player_id].mission = mission
            self.players[player_id].setup_troops_left = 40
            self.players[player_id].reinforcements_to_place = 0
            self.players[player_id].alive = True
            self.players[player_id].hand.clear()
            self.players[player_id].ready = True
        for territory in self.territories.values():
            territory["owner"] = None
            territory["troops"] = 0
        cards = build_territory_cards(self.board)
        territory_cards = [card for card in cards if card["kind"] == "territory"]
        wild_cards = [card for card in cards if card["kind"] == "wild"]
        self._rng.shuffle(territory_cards)
        split = len(territory_cards) // 2
        initial_hands = {
            player_ids[0]: territory_cards[:split],
            player_ids[1]: territory_cards[split:],
        }
        for player_id, hand in initial_hands.items():
            for card in hand:
                territory_id = str(card["territory"])
                self.territories[territory_id]["owner"] = player_id
                self.territories[territory_id]["troops"] = 1
                self.players[player_id].setup_troops_left -= 1
        draw_cards = territory_cards + wild_cards
        self._rng.shuffle(draw_cards)
        self.draw_deck = draw_cards
        self.discard_pile.clear()
        self.phase = "setup"
        roll_one = self._rng.randint(1, 6)
        roll_two = self._rng.randint(1, 6)
        while roll_one == roll_two:
            roll_one = self._rng.randint(1, 6)
            roll_two = self._rng.randint(1, 6)
        self.first_player_id = player_ids[0] if roll_one > roll_two else player_ids[1]
        self.current_player_id = self.first_player_id
        self.pending_prompt = None
        self.pending_battle = None
        self.global_trade_count = 0
        self.turn_conquest_happened = False
        self.turn_card_awarded = False
        self.fortify_used = False
        first_name = self.players[self.first_player_id].name
        self.log_entries.clear()
        self._log(
            f"A partida começou. {self.players[player_ids[0]].name} tirou {roll_one}, "
            f"{self.players[player_ids[1]].name} tirou {roll_two}. {first_name} começa."
        )
        self._set_status(f"Fase de preparação: {first_name} coloca 1 tropa em um de seus territórios.")

    def _advance_setup_turn(self) -> None:
        if all(player.setup_troops_left == 0 for player in self.players.values()):
            if not self.first_player_id:
                raise RuntimeError("O primeiro jogador não foi inicializado.")
            self._start_turn(self.first_player_id)
            return
        others = [pid for pid in self.players if pid != self.current_player_id]
        next_player_id = next(
            (pid for pid in others if self.players[pid].setup_troops_left > 0),
            self.current_player_id,
        )
        if next_player_id == self.current_player_id and self.players[next_player_id].setup_troops_left == 0:
            next_player_id = others[0]
        self.current_player_id = next_player_id
        self._set_status(
            f"Fase de preparação: {self.players[self.current_player_id].name} coloca 1 tropa."
        )

    def _start_turn(self, player_id: str) -> None:
        self.current_player_id = player_id
        self.phase = "reinforcement"
        self.pending_prompt = None
        self.pending_battle = None
        self.turn_conquest_happened = False
        self.turn_card_awarded = False
        self.fortify_used = False
        reinforcement = reinforcement_total(player_id, self.territories, self.board)
        player = self.players[player_id]
        player.reinforcements_to_place = int(reinforcement["total"])
        self._set_status(
            f"Turno de {player.name}: {player.reinforcements_to_place} tropa(s) de reforço para posicionar."
        )
        self._log(
            f"{player.name} inicia o turno com {reinforcement['total']} reforços "
            f"({reinforcement['base']} de base + {reinforcement['continent_bonus']} de bônus continental)."
        )
        self._check_winner(player_id)

    def _player_territories(self, player_id: str) -> list[str]:
        return [
            territory_id
            for territory_id, territory in self.territories.items()
            if territory["owner"] == player_id
        ]

    def _draw_card(self) -> dict[str, object] | None:
        if not self.draw_deck and self.discard_pile:
            self.draw_deck = self.discard_pile[:]
            self.discard_pile.clear()
            self._rng.shuffle(self.draw_deck)
        return self.draw_deck.pop() if self.draw_deck else None

    def _check_winner(self, player_id: str) -> None:
        if self.phase == "game_over":
            return
        player = self.players[player_id]
        mission = player.mission
        if mission and mission_completed(player_id, mission, self.territories, self.board):
            self._declare_winner(player_id, f"{player.name} completou a missão secreta.")

    def _declare_winner(self, winner_id: str | None, reason: str) -> None:
        self.phase = "game_over"
        self.pending_prompt = None
        self.pending_battle = None
        self.winner_id = winner_id
        self.status_message = reason
        if winner_id and winner_id in self.players:
            self._log(f"{self.players[winner_id].name} venceu. {reason}")
        else:
            self._log(reason)

    def _set_status(self, message: str) -> None:
        self.status_message = message

    def _log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_entries.append(f"[{timestamp}] {message}")

    def _bump_version(self) -> None:
        self.version += 1

    def _build_snapshot(self, viewer_id: str) -> dict[str, object]:
        viewer = self.players[viewer_id]
        trade_sets = enumerate_trade_sets(viewer.hand)
        player_rows = []
        for player in self.players.values():
            territories = self._player_territories(player.player_id)
            troops = sum(int(self.territories[territory_id]["troops"]) for territory_id in territories)
            row = {
                "player_id": player.player_id,
                "name": player.name,
                "color": player.color,
                "ready": player.ready,
                "territory_count": len(territories),
                "troop_count": troops,
                "card_count": len(player.hand),
                "alive": player.alive,
                "is_current": player.player_id == self.current_player_id,
                "owned_continents": owned_continents(player.player_id, self.territories, self.board),
            }
            if player.player_id == viewer_id and player.mission:
                row["mission"] = deepcopy(player.mission)
            player_rows.append(row)
        territories_payload = []
        for territory_id in self.board.territories_in_order:
            definition = self.board.territories[territory_id]
            state = self.territories[territory_id]
            territories_payload.append(
                {
                    "territory_id": territory_id,
                    "display_name": definition.display_name,
                    "continent": definition.continent,
                    "label_x": definition.label_x,
                    "label_y": definition.label_y,
                    "polygon": [[x, y] for x, y in definition.polygon],
                    "neighbors": list(definition.neighbors),
                    "special_neighbors": list(definition.special_neighbors),
                    "owner": state["owner"],
                    "troops": int(state["troops"]),
                }
            )
        prompt = deepcopy(self.pending_prompt) if self.pending_prompt else None
        if prompt and prompt.get("target_player_id") != viewer_id:
            prompt = None
        hand_payload = [
            {
                "id": str(card["id"]),
                "territory": card["territory"],
                "symbol": card["symbol"],
                "kind": card["kind"],
            }
            for card in viewer.hand
        ]
        return {
            "version": self.version,
            "phase": self.phase,
            "status_message": self.status_message,
            "current_player_id": self.current_player_id,
            "winner_id": self.winner_id,
            "self_player_id": viewer_id,
            "players": player_rows,
            "territories": territories_payload,
            "your_hand": hand_payload,
            "your_trade_sets": trade_sets,
            "must_trade": player_must_trade(len(viewer.hand)) and bool(trade_sets),
            "reinforcements_to_place": viewer.reinforcements_to_place,
            "setup_troops_left": viewer.setup_troops_left,
            "pending_prompt": prompt,
            "last_battle": deepcopy(self.last_battle),
            "log": self.log_entries[-12:],
            "full_log": self.log_entries[:],
            "board": {
                "width": self.board.width,
                "height": self.board.height,
                "special_edges": [list(edge) for edge in self.board.special_edges()],
            },
            "global_trade_count": self.global_trade_count,
            "draw_deck_count": len(self.draw_deck),
        }
