"""Interface pygame do jogo Risk distribuído."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pygame

from risk_dist.client.network import RpcGameClient, normalize_endpoint
from risk_dist.shared.board import load_board, point_in_polygon
from risk_dist.shared.constants import (
    BOARD_ASSET_PATH,
    CONTINENT_BONUSES,
    CONTINENT_COLORS,
    CONTINENT_LABELS,
    DEFAULT_PORT,
    PLAYER_COLORS,
    PLAYER_COLOR_LABELS,
    SNAPSHOT_POLL_MS,
)


OUTER_MARGIN = 8
PANEL_GAP = 8
LEFT_SIDEBAR_WIDTH = 184
RIGHT_SIDEBAR_WIDTH = 302
BOARD_RENDER_WIDTH = 1070
WINDOW_SIZE = (
    OUTER_MARGIN
    + LEFT_SIDEBAR_WIDTH
    + PANEL_GAP
    + BOARD_RENDER_WIDTH
    + PANEL_GAP
    + RIGHT_SIDEBAR_WIDTH
    + OUTER_MARGIN,
    900,
)
WINDOW_RATIO = 0.70
BACKGROUND = (15, 17, 22)
PANEL = (26, 31, 40)
PANEL_ALT = (35, 42, 55)
TEXT = (236, 238, 241)
SUBTLE = (175, 182, 194)
ACCENT = (79, 187, 255)
ERROR = (224, 91, 91)
SUCCESS = (93, 204, 123)

CARD_SYMBOL_LABELS = {
    "infantry": "Infantaria",
    "cavalry": "Cavalaria",
    "artillery": "Artilharia",
    "wild": "Curinga",
}

RULES_PAGES = (
    (
        "Objetivo",
        (
            "Vença sendo o primeiro jogador a cumprir sua missão secreta.",
            "A missão fica visível apenas para o próprio jogador.",
            "O tabuleiro fica visível para todos, mas cartas e missão são informações privadas do dono.",
        ),
    ),
    (
        "Preparação",
        (
            "Cada jogador escolhe uma cor e recebe tropas iniciais.",
            "Infantaria vale 1 tropa, cavalaria vale 5 tropas e artilharia vale 10 tropas na representação visual.",
            "As cartas de território são distribuídas sem os curingas; cada território começa com 1 infantaria.",
            "Depois, os jogadores posicionam tropas extras em rodízio nos próprios territórios.",
            "Quando a preparação termina, os curingas voltam ao baralho de território.",
        ),
    ),
    (
        "Turno e Reforços",
        (
            "No início do turno, receba o número de territórios dividido por 3, sempre com mínimo de 3 tropas.",
            "Dominar um continente inteiro concede tropas extras conforme a legenda.",
            "Distribua todos os reforços antes de atacar.",
            "Depois dos reforços vem a fase de ataque; você pode atacar várias vezes na mesma fase.",
            "Quando não for sua vez, aguarde a ação do outro jogador.",
        ),
    ),
    (
        "Cartas e Curingas",
        (
            "Você recebe 1 carta no fim do turno se conquistou pelo menos 1 território naquele turno.",
            "Mesmo conquistando vários territórios, o limite é 1 carta por turno.",
            "Cartas de território têm símbolo de infantaria, cavalaria ou artilharia.",
            "A carta curinga não representa território; ela pode substituir qualquer símbolo em uma troca.",
            "O curinga não concede bônus de +2 tropas em território específico.",
            "Trocas válidas são 3 símbolos iguais, 1 de cada símbolo ou combinações usando curingas.",
            "O valor das trocas aumenta globalmente: 4, 6, 8, 10, 12, 15 e depois soma +5.",
        ),
    ),
    (
        "Ataque e Dados",
        (
            "Você pode atacar várias vezes na mesma fase de ataque.",
            "Para atacar, selecione primeiro um território seu com pelo menos 2 tropas.",
            "Depois selecione um território inimigo adjacente ou ligado por linha tracejada.",
            "O atacante usa até 3 dados, limitado pelas tropas disponíveis; o defensor usa 1 ou 2 dados.",
            "Os maiores dados são comparados. Empate favorece o defensor.",
            "Dados vermelhos são do atacante; dados azuis são do defensor.",
        ),
    ),
    (
        "Conquista",
        (
            "Se o defensor perder a última tropa, o território é conquistado.",
            "O atacante deve mover tropas para o território conquistado.",
            "O número mínimo de tropas movidas é o número de dados usados no ataque final.",
            "Após a conquista, você ainda pode continuar atacando na mesma fase.",
        ),
    ),
    (
        "Manobra e Vitória",
        (
            "Após encerrar os ataques, você pode fazer uma única manobra.",
            "A manobra move tropas entre dois territórios seus conectados por caminho próprio.",
            "O território de origem precisa ficar com pelo menos 1 tropa.",
            "Ao eliminar um oponente, você recebe todas as cartas dele.",
            "Se ficar com mais de 4 cartas, deve realizar trocas imediatas.",
            "A partida termina assim que uma missão secreta for cumprida.",
        ),
    ),
)


@dataclass(frozen=True)
class ConfiguracaoCliente:
    nome_inicial: str = "Jogador"
    servidor_inicial: str = f"127.0.0.1:{DEFAULT_PORT}"
    autoconectar: bool = False
    cor_automatica: str | None = None
    pronto_automatico: bool = False
    posicao_janela: tuple[int, int] | None = None


@dataclass
class Button:
    rect: pygame.Rect
    label: str
    action: tuple[str, object | None]
    enabled: bool = True

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        bg = ACCENT if self.enabled else (65, 76, 91)
        pygame.draw.rect(surface, bg, self.rect, border_radius=10)
        pygame.draw.rect(surface, (255, 255, 255), self.rect, width=1, border_radius=10)
        label = fit_text(self.label, font, self.rect.width - 16)
        text_surface = font.render(label, True, (10, 15, 20) if self.enabled else (170, 170, 170))
        surface.blit(text_surface, text_surface.get_rect(center=self.rect.center))


class TextInput:
    def __init__(self, rect: pygame.Rect, text: str = "", placeholder: str = "") -> None:
        self.rect = rect
        self.text = text
        self.placeholder = placeholder
        self.active = False

    def handle_event(self, event: pygame.event.Event, mouse_pos: tuple[int, int] | None = None) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(mouse_pos or event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                self.active = False
            elif event.unicode and len(self.text) < 64 and event.unicode.isprintable():
                self.text += event.unicode

    def draw(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        pygame.draw.rect(surface, PANEL_ALT if self.active else PANEL, self.rect, border_radius=10)
        pygame.draw.rect(surface, ACCENT if self.active else SUBTLE, self.rect, width=2, border_radius=10)
        display = self.text or self.placeholder
        color = TEXT if self.text else SUBTLE
        display = fit_text(display, font, self.rect.width - 24)
        text_surface = font.render(display, True, color)
        surface.blit(text_surface, (self.rect.x + 12, self.rect.y + 10))


class RiskClientApp:
    def __init__(self, configuracao: ConfiguracaoCliente | None = None) -> None:
        self.configuracao = configuracao or ConfiguracaoCliente()
        if self.configuracao.posicao_janela:
            pos_x, pos_y = self.configuracao.posicao_janela
            os.environ["SDL_VIDEO_WINDOW_POS"] = f"{pos_x},{pos_y}"
        pygame.init()
        pygame.display.set_caption("Risk Distribuído")
        self.window_size = calcular_tamanho_janela()
        self.window = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
        self.screen = pygame.Surface(WINDOW_SIZE).convert()
        self.viewport_rect = self._calcular_viewport()
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("verdana", 18)
        self.font_small = pygame.font.SysFont("verdana", 14)
        self.font_tiny = pygame.font.SysFont("verdana", 12, bold=True)
        self.font_big = pygame.font.SysFont("verdana", 30, bold=True)
        board_path = Path(BOARD_ASSET_PATH)
        self.board_image = pygame.image.load(str(board_path)).convert()
        self.board_definition = load_board()
        self.client: RpcGameClient | None = None
        self.server_process: subprocess.Popen[bytes] | None = None
        self.local_server_port: int | None = None
        self.snapshot: dict[str, object] | None = None
        self.snapshot_version: int | None = None
        self.last_poll_ms = 0
        self.running = True
        self.state = "menu"
        self.message = "Hospede uma partida ou conecte-se a um servidor na rede local."
        self.message_color = SUBTLE
        self.name_input = TextInput(
            pygame.Rect(80, 190, 420, 44),
            self.configuracao.nome_inicial,
            "Nome do jogador",
        )
        self.host_input = TextInput(
            pygame.Rect(80, 270, 420, 44),
            self.configuracao.servidor_inicial,
            "Servidor (IP:porta)",
        )
        self.menu_buttons: list[Button] = []
        self.game_buttons: list[Button] = []
        self.lobby_buttons: list[Button] = []
        self.card_rects: dict[str, pygame.Rect] = {}
        self.selected_cards: set[str] = set()
        self.selected_territories: list[str] = []
        self.move_count = 0
        self.rules_visible = False
        self.rules_page = 0
        self._last_prompt_signature: tuple[str, int, int] | None = None
        self.board_cache: dict[tuple[int, int], pygame.Surface] = {}
        if self.configuracao.autoconectar:
            self._connect_to_server(self.host_input.text)

    def run(self) -> None:
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    continue
                if event.type == pygame.VIDEORESIZE:
                    self.window_size = (max(640, event.w), max(360, event.h))
                    self.window = pygame.display.set_mode(self.window_size, pygame.RESIZABLE)
                    self.viewport_rect = self._calcular_viewport()
                    continue
                self._handle_event(event)
            self._poll_snapshot_if_needed()
            self._draw()
            self._present()
            pygame.display.flip()
            self.clock.tick(60)
        self._shutdown()

    def _handle_event(self, event: pygame.event.Event) -> None:
        mouse_pos = self._to_virtual_pos(event.pos) if hasattr(event, "pos") else None
        if self.state == "menu":
            self.name_input.handle_event(event, mouse_pos)
            self.host_input.handle_event(event, mouse_pos)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and mouse_pos:
                for button in self.menu_buttons:
                    if button.enabled and button.rect.collidepoint(mouse_pos):
                        self._activate(button.action)
        elif self.state == "lobby":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and mouse_pos:
                for button in self.lobby_buttons:
                    if button.enabled and button.rect.collidepoint(mouse_pos):
                        self._activate(button.action)
        elif self.state == "game":
            if self.rules_visible:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.rules_visible = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and mouse_pos:
                    for button in reversed(self.game_buttons):
                        if button.action[0] in {"close_rules", "rules_page"} and button.enabled and button.rect.collidepoint(mouse_pos):
                            self._activate(button.action)
                            return
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and mouse_pos:
                if self._handle_game_click(mouse_pos):
                    return
                territory_id = self._territory_at_pos(mouse_pos)
                if territory_id:
                    self._handle_territory_click(territory_id)
                else:
                    self.selected_territories.clear()

    def _activate(self, action: tuple[str, object | None]) -> None:
        kind, value = action
        if kind == "host":
            self._host_game()
        elif kind == "join":
            self._connect_to_server(str(value or self.host_input.text))
        elif kind == "show_rules":
            self.rules_visible = True
        elif kind == "close_rules":
            self.rules_visible = False
        elif kind == "rules_page":
            self.rules_page = max(0, min(len(RULES_PAGES) - 1, self.rules_page + int(value or 0)))
        elif kind == "choose_color":
            assert self.client
            result = self.client.choose_color(str(value))
            self._set_result_message(result, success="Cor selecionada.")
        elif kind == "ready":
            assert self.client
            result = self.client.ready()
            self._set_result_message(result, success="Pronto confirmado.")
        elif kind == "trade_selected":
            assert self.client
            result = self.client.submit_action("trade_cards", {"card_ids": sorted(self.selected_cards)})
            if result.get("ok"):
                self.selected_cards.clear()
            self._set_result_message(result, success="Cartas trocadas.")
        elif kind == "auto_trade":
            assert self.client
            trade_sets = list(self.snapshot.get("your_trade_sets", [])) if self.snapshot else []
            if trade_sets:
                result = self.client.submit_action("trade_cards", {"card_ids": trade_sets[0]})
                self.selected_cards.clear()
                self._set_result_message(result, success="Cartas trocadas.")
        elif kind == "attack":
            assert self.client
            source, target = self.selected_territories[:2]
            result = self.client.submit_action("attack", {"from": source, "to": target, "dice": int(value)})
            self._set_result_message(result, success="Ataque enviado.")
        elif kind == "defend":
            assert self.client
            result = self.client.submit_action("defend", {"dice": int(value)})
            self._set_result_message(result, success="Defesa enviada.")
        elif kind == "move_delta":
            prompt = self.snapshot.get("pending_prompt") if self.snapshot else None
            if not prompt:
                return
            min_troops = int(prompt["min_troops"])
            max_troops = int(prompt["max_troops"])
            self.move_count = max(min_troops, min(max_troops, self.move_count + int(value)))
        elif kind == "capture_move":
            assert self.client
            result = self.client.submit_action("capture_move", {"count": self.move_count})
            self._set_result_message(result, success="Movimentação de conquista confirmada.")
        elif kind == "fortify":
            assert self.client
            source, target = self.selected_territories[:2]
            result = self.client.submit_action(
                "fortify",
                {"from": source, "to": target, "count": self.move_count},
            )
            self._set_result_message(result, success="Manobra enviada.")
        elif kind == "end_attack_phase":
            assert self.client
            result = self.client.submit_action("end_attack_phase", {})
            self._set_result_message(result, success="Fase de ataque encerrada.")
        elif kind == "end_turn":
            assert self.client
            result = self.client.submit_action("end_turn", {})
            self._set_result_message(result, success="Turno encerrado.")

    def _host_game(self) -> None:
        if self.server_process is None:
            porta = escolher_porta_local_livre(DEFAULT_PORT)
            self.local_server_port = porta
            self.host_input.text = f"127.0.0.1:{porta}"
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "risk_dist.server", "--host", "0.0.0.0", "--port", str(porta)]
            )
            start = time.time()
            while time.time() - start < 3:
                if self.server_process.poll() is not None:
                    self.server_process = None
                    self.local_server_port = None
                    self._set_message("O processo do servidor local foi encerrado antes de iniciar.", ERROR)
                    return
                try:
                    self._connect_to_server(f"127.0.0.1:{porta}", silent=True)
                    self._set_message("Servidor local iniciado.", SUCCESS)
                    return
                except RuntimeError:
                    time.sleep(0.15)
            self._set_message("O servidor iniciou, mas ainda não foi possível conectar.", SUBTLE)
        else:
            if self.server_process.poll() is not None:
                self.server_process = None
                self.local_server_port = None
                self._host_game()
                return
            self._connect_to_server(f"127.0.0.1:{self.local_server_port or DEFAULT_PORT}")

    def _connect_to_server(self, endpoint_text: str, silent: bool = False) -> None:
        host, port, endpoint = normalize_endpoint(endpoint_text)
        client = RpcGameClient(endpoint=endpoint)
        result = client.connect(self.name_input.text.strip() or "Jogador")
        if not result.get("ok"):
            self.client = None
            if silent:
                raise RuntimeError(str(result.get("error", "falha na conexão")))
            self._set_result_message(result)
            return
        self.client = client
        self.state = "lobby"
        self.snapshot = None
        self.snapshot_version = None
        self.selected_cards.clear()
        self.selected_territories.clear()
        self._set_message(f"Conectado a {host}:{port}.", SUCCESS)

    def _poll_snapshot_if_needed(self) -> None:
        if not self.client:
            return
        now = pygame.time.get_ticks()
        if now - self.last_poll_ms < SNAPSHOT_POLL_MS:
            return
        self.last_poll_ms = now
        result = self.client.poll_snapshot(self.snapshot_version)
        if result.get("ok") is False or result.get("error"):
            self._set_result_message(result)
            return
        if not result.get("updated") and result.get("snapshot") is None:
            return
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict):
            self._set_result_message(result)
            return
        if snapshot.get("error"):
            self._set_message(str(snapshot["error"]), ERROR)
            return
        self.snapshot_version = int(result["version"])
        self.snapshot = snapshot
        self._ingest_snapshot(snapshot)

    def _ingest_snapshot(self, snapshot: dict[str, object]) -> None:
        self.selected_cards &= {str(card["id"]) for card in snapshot.get("your_hand", [])}
        if snapshot.get("phase") == "lobby":
            self.state = "lobby"
        else:
            self.state = "game"
        if self.state == "lobby":
            self._aplicar_acoes_automaticas_no_lobby(snapshot)
        prompt = snapshot.get("pending_prompt") or {}
        if isinstance(prompt, dict) and prompt.get("type") == "capture_move":
            signature = (
                str(prompt["from"]),
                int(prompt["min_troops"]),
                int(prompt["max_troops"]),
            )
            if signature != self._last_prompt_signature:
                self.move_count = int(prompt["min_troops"])
                self._last_prompt_signature = signature
        elif isinstance(prompt, dict) and prompt.get("type") == "fortify":
            self._last_prompt_signature = None
        if snapshot.get("winner_id"):
            winner_name = next(
                (player["name"] for player in snapshot["players"] if player["player_id"] == snapshot["winner_id"]),
                "Desconhecido",
            )
            self._set_message(f"Fim de jogo. Vencedor: {winner_name}.", SUCCESS)

    def _aplicar_acoes_automaticas_no_lobby(self, snapshot: dict[str, object]) -> None:
        if not self.client:
            return
        eu = next(
            (player for player in snapshot.get("players", []) if player.get("player_id") == snapshot.get("self_player_id")),
            None,
        )
        if not isinstance(eu, dict):
            return
        cor_automatica = self.configuracao.cor_automatica
        if cor_automatica and eu.get("color") != cor_automatica:
            disponivel = all(player.get("color") != cor_automatica for player in snapshot.get("players", []))
            if disponivel:
                resultado = self.client.choose_color(cor_automatica)
                if resultado.get("ok"):
                    self._set_message(f"Cor automática selecionada: {PLAYER_COLOR_LABELS.get(cor_automatica, cor_automatica)}.", SUCCESS)
                    return
        if self.configuracao.pronto_automatico and eu.get("color") and not eu.get("ready"):
            resultado = self.client.ready()
            if resultado.get("ok"):
                self._set_message("Pronto automático confirmado.", SUCCESS)

    def _draw(self) -> None:
        self.screen.fill(BACKGROUND)
        if self.state == "menu":
            self._draw_menu()
        elif self.state == "lobby":
            self._draw_lobby()
        elif self.state == "game":
            self._draw_game()

    def _present(self) -> None:
        self.window.fill(BACKGROUND)
        frame = pygame.transform.smoothscale(self.screen, self.viewport_rect.size)
        self.window.blit(frame, self.viewport_rect.topleft)

    def _draw_menu(self) -> None:
        self.menu_buttons = [
            Button(pygame.Rect(80, 360, 180, 48), "Hospedar Partida", ("host", None)),
            Button(pygame.Rect(280, 360, 180, 48), "Entrar na Partida", ("join", self.host_input.text)),
        ]
        title = self.font_big.render("Risk Distribuído", True, TEXT)
        self.screen.blit(title, (80, 90))
        self.screen.blit(self.font.render("Nome do jogador", True, SUBTLE), (80, 160))
        self.screen.blit(self.font.render("Servidor (IP:porta)", True, SUBTLE), (80, 240))
        self.name_input.draw(self.screen, self.font)
        self.host_input.draw(self.screen, self.font)
        for button in self.menu_buttons:
            button.draw(self.screen, self.font)
        self._draw_message(80, 430, 500)
        hint_lines = wrap_text(
            "Use Hospedar em uma máquina. O outro cliente entra usando o IP local do anfitrião.",
            self.font_small,
            500,
            max_lines=2,
        )
        for index, line in enumerate(hint_lines):
            self.screen.blit(self.font_small.render(line, True, SUBTLE), (80, 470 + index * 16))

    def _draw_lobby(self) -> None:
        self.lobby_buttons = []
        title = self.font_big.render("Sala", True, TEXT)
        self.screen.blit(title, (60, 40))
        self._draw_panel(pygame.Rect(40, 100, 600, 280))
        self._draw_message(60, 320, 560)
        snapshot = self.snapshot or {}
        players = list(snapshot.get("players", []))
        colors_y = 190
        self.screen.blit(self.font.render("Escolha uma cor", True, TEXT), (60, 150))
        x = 60
        for color_name, color_value in PLAYER_COLORS.items():
            button_rect = pygame.Rect(x, colors_y, 96, 40)
            available = all(player.get("color") != color_name for player in players) or any(
                player.get("player_id") == snapshot.get("self_player_id") and player.get("color") == color_name
                for player in players
            )
            fill = color_value if available else tuple(max(40, channel // 2) for channel in color_value)
            pygame.draw.rect(self.screen, fill, button_rect, border_radius=10)
            pygame.draw.rect(self.screen, TEXT, button_rect, width=1, border_radius=10)
            label = self.font_small.render(PLAYER_COLOR_LABELS.get(color_name, color_name.title()), True, (10, 10, 10))
            self.screen.blit(label, label.get_rect(center=button_rect.center))
            self.lobby_buttons.append(Button(button_rect, PLAYER_COLOR_LABELS.get(color_name, color_name.title()), ("choose_color", color_name), available))
            x += 110
        ready_rect = pygame.Rect(60, 260, 170, 46)
        self.lobby_buttons.append(Button(ready_rect, "Ficar Pronto", ("ready", None), True))
        for button in self.lobby_buttons:
            if button.action[0] == "ready":
                button.draw(self.screen, self.font)
        roster_y = 420
        self.screen.blit(self.font.render("Jogadores", True, TEXT), (60, roster_y))
        for index, player in enumerate(players):
            color = PLAYER_COLORS.get(str(player.get("color")), SUBTLE)
            row_rect = pygame.Rect(60, roster_y + 40 + index * 56, 520, 44)
            self._draw_panel(row_rect, PANEL_ALT)
            pygame.draw.circle(self.screen, color, (row_rect.x + 22, row_rect.centery), 12)
            cor = PLAYER_COLOR_LABELS.get(str(player.get("color")), "Sem cor") if player.get("color") else "Sem cor"
            pronto = "Pronto" if player.get("ready") else "Aguardando"
            primary = fit_text(f"{player.get('name')} | {cor}", self.font_small, row_rect.width - 56)
            secondary = fit_text(pronto, self.font_tiny, row_rect.width - 56)
            self.screen.blit(self.font_small.render(primary, True, TEXT), (row_rect.x + 42, row_rect.y + 5))
            self.screen.blit(self.font_tiny.render(secondary, True, SUBTLE), (row_rect.x + 42, row_rect.y + 24))

    def _draw_game(self) -> None:
        snapshot = self.snapshot or {}
        self.game_buttons = []
        board_rect, scale = self._board_rect()
        scaled_board = self._scaled_board_image(board_rect.size)
        self.screen.blit(scaled_board, board_rect.topleft)
        self._draw_board_overlays(board_rect, scale, snapshot)
        self._draw_left_sidebar(snapshot)
        self._draw_sidebar(snapshot, board_rect)
        self._draw_board_action_bar(snapshot, board_rect)
        if self.rules_visible:
            self._draw_rules_modal()

    def _draw_sidebar(self, snapshot: dict[str, object], board_rect: pygame.Rect) -> None:
        sidebar = pygame.Rect(board_rect.right + PANEL_GAP, 20, RIGHT_SIDEBAR_WIDTH, WINDOW_SIZE[1] - 40)
        self._draw_panel(sidebar)
        status_box = pygame.Rect(sidebar.x + 10, sidebar.y + 10, sidebar.width - 20, 82)
        self._draw_panel(status_box, PANEL_ALT)
        self._draw_section_header("Situação", status_box.x + 10, status_box.y + 8, status_box.width - 20)
        status_lines = wrap_text(str(snapshot.get("status_message", "")), self.font_small, status_box.width - 20, max_lines=3)
        for index, line in enumerate(status_lines):
            self.screen.blit(self.font_small.render(line, True, TEXT), (status_box.x + 10, status_box.y + 36 + index * 15))
        cursor_y = status_box.bottom + 12
        cursor_y = self._draw_section_header("Jogadores", sidebar.x + 12, cursor_y, sidebar.width - 24)
        cursor_y += self._draw_players_block(snapshot, sidebar.x + 12, cursor_y, sidebar.width - 24) + 10
        self._draw_mission_block(snapshot, sidebar.x + 12, cursor_y, sidebar.width - 24)
        cursor_y += 110
        self._draw_prompt_and_buttons(snapshot, sidebar.x + 12, cursor_y, sidebar.width - 24)
        cursor_y += 170
        self._draw_hand(snapshot, sidebar.x + 12, cursor_y, sidebar.width - 24)
        cursor_y += 210
        self._draw_log(snapshot, sidebar.x + 12, cursor_y, sidebar.width - 24, sidebar.bottom - cursor_y - 12)

    def _draw_players_block(self, snapshot: dict[str, object], x: int, y: int, width: int) -> int:
        row_height = 80
        players = list(snapshot.get("players", []))
        for index, player in enumerate(players):
            row = pygame.Rect(x, y + index * row_height, width, row_height - 8)
            self._draw_panel(row, PANEL_ALT)
            color = PLAYER_COLORS.get(str(player.get("color")), SUBTLE)
            pygame.draw.circle(self.screen, color, (row.x + 18, row.centery), 10)
            prefix = ">> " if player.get("is_current") else ""
            color_name = PLAYER_COLOR_LABELS.get(str(player.get("color")), "Sem cor")
            name_line = fit_text(f"{prefix}{player.get('name')} | {color_name}", self.font_small, width - 52)
            stats_line = fit_text(
                f"Territórios: {player.get('territory_count')} | Exércitos: {player.get('troop_count')}",
                self.font_tiny,
                width - 52,
            )
            cards_line = fit_text(f"Cartas: {player.get('card_count')}", self.font_tiny, width - 52)
            self.screen.blit(self.font_small.render(name_line, True, TEXT), (row.x + 36, row.y + 7))
            self.screen.blit(self.font_tiny.render(stats_line, True, SUBTLE), (row.x + 36, row.y + 29))
            self.screen.blit(self.font_tiny.render(cards_line, True, SUBTLE), (row.x + 36, row.y + 43))
            continents = ", ".join(CONTINENT_LABELS.get(continent, continent) for continent in player.get("owned_continents", []))
            if continents:
                continent_line = fit_text(continents, self.font_tiny, width - 52)
                self.screen.blit(self.font_tiny.render(continent_line, True, SUBTLE), (row.x + 36, row.y + 57))
        return max(0, len(players) * row_height - 8)

    def _draw_left_sidebar(self, snapshot: dict[str, object]) -> None:
        box = pygame.Rect(OUTER_MARGIN, 20, LEFT_SIDEBAR_WIDTH, WINDOW_SIZE[1] - 40)
        self._draw_panel(box)
        player = self._self_player(snapshot)
        color_name = PLAYER_COLOR_LABELS.get(str(player.get("color")), "Sem cor") if player else "Sem cor"
        display_name = str(player.get("name", "Desconhecido")) if player else "Desconhecido"
        color = PLAYER_COLORS.get(str(player.get("color")), SUBTLE) if player else SUBTLE

        player_box = pygame.Rect(box.x + 10, box.y + 10, box.width - 20, 96)
        legend_box = pygame.Rect(box.x + 10, player_box.bottom + 10, box.width - 20, box.bottom - player_box.bottom - 20)
        self._draw_panel(player_box, PANEL_ALT)
        self._draw_panel(legend_box, PANEL_ALT)

        self._draw_section_header("Você é o jogador", player_box.x + 10, player_box.y + 8, player_box.width - 20)
        pygame.draw.circle(self.screen, color, (player_box.x + 20, player_box.y + 52), 8)
        for index, line in enumerate(wrap_text(display_name, self.font_small, player_box.width - 38, max_lines=2)):
            self.screen.blit(self.font_small.render(line, True, TEXT), (player_box.x + 34, player_box.y + 40 + index * 16))
        self.screen.blit(self.font_tiny.render(f"Cor: {color_name}", True, SUBTLE), (player_box.x + 34, player_box.y + 74))

        self._draw_section_header("Legenda dos continentes", legend_box.x + 10, legend_box.y + 8, legend_box.width - 20)
        entries = list(CONTINENT_COLORS.items())
        for index, (continent, entry_color) in enumerate(entries):
            row = pygame.Rect(legend_box.x + 8, legend_box.y + 36 + index * 42, legend_box.width - 16, 34)
            self._draw_panel(row, PANEL)
            pygame.draw.circle(self.screen, entry_color, (row.x + 12, row.centery), 6)
            label = f"{CONTINENT_LABELS.get(continent, continent)} (+{CONTINENT_BONUSES[continent]})"
            for line_index, line in enumerate(wrap_text(label, self.font_tiny, row.width - 30, max_lines=2)):
                self.screen.blit(self.font_tiny.render(line, True, TEXT), (row.x + 24, row.y + 4 + line_index * 12))

    def _draw_mission_block(self, snapshot: dict[str, object], x: int, y: int, width: int) -> None:
        box = pygame.Rect(x, y, width, 100)
        self._draw_panel(box, PANEL_ALT)
        self._draw_section_header("Missão", x + 10, y + 8, width - 20)
        mission = None
        for player in snapshot.get("players", []):
            if player.get("player_id") == snapshot.get("self_player_id"):
                mission = player.get("mission")
                break
        lines = wrap_text(
            str(mission.get("label", "Aguardando missão...") if mission else "Aguardando missão..."),
            self.font_small,
            width - 20,
            max_lines=4,
        )
        for index, line in enumerate(lines[:4]):
            self.screen.blit(self.font_small.render(line, True, SUBTLE), (x + 10, y + 38 + index * 16))

    def _draw_prompt_and_buttons(self, snapshot: dict[str, object], x: int, y: int, width: int) -> None:
        box = pygame.Rect(x, y, width, 156)
        self._draw_panel(box, PANEL_ALT)
        self._draw_section_header("Orientação", x + 10, y + 8, width - 20)
        self._draw_message(x + 10, y + 38, width - 20, max_lines=2)
        for index, line in enumerate(wrap_text(self._phase_instruction(snapshot), self.font_tiny, width - 20, max_lines=3)):
            self.screen.blit(self.font_tiny.render(line, True, SUBTLE), (x + 10, y + 74 + index * 14))
        prompt = snapshot.get("pending_prompt") or {}
        if isinstance(prompt, dict) and prompt.get("type") == "capture_move":
            hint = fit_text(f"Mover tropas: {self.move_count}", self.font_small, width - 132)
            self.screen.blit(self.font_small.render(hint, True, TEXT), (x + 10, y + 118))
        elif self.selected_territories:
            label = "Selecionado: " + ", ".join(self._territory_name(snapshot, territory_id) for territory_id in self.selected_territories)
            label = fit_text(label, self.font_small, width - 132)
            self.screen.blit(self.font_small.render(label, True, SUBTLE), (x + 10, y + 118))
        rules_button = Button(pygame.Rect(x + width - 108, y + 116, 98, 30), "Regras", ("show_rules", None))
        self.game_buttons.append(rules_button)
        rules_button.draw(self.screen, self.font_small)

    def _draw_board_action_bar(self, snapshot: dict[str, object], board_rect: pygame.Rect) -> None:
        bar = pygame.Rect(board_rect.x, board_rect.bottom + 8, board_rect.width, WINDOW_SIZE[1] - board_rect.bottom - 28)
        self._draw_panel(bar, PANEL_ALT)
        info_width = 392
        hover_pos = self._virtual_mouse_pos()
        hover = self._territory_at_pos(hover_pos) if hover_pos else None
        if hover:
            territory = self._territory(snapshot, hover)
            info = f"{territory['display_name']} | tropas: {territory['troops']}"
        else:
            info = self._bottom_bar_instruction(snapshot)
        for index, line in enumerate(wrap_text(info, self.font_small, info_width, max_lines=2)):
            self.screen.blit(self.font_small.render(line, True, TEXT if index == 0 else SUBTLE), (bar.x + 12, bar.y + 10 + index * 17))

        buttons = self._build_game_buttons(snapshot, bar.x + info_width + 24, bar.y + 12, bar.width - info_width - 36)
        self.game_buttons.extend(buttons)
        for button in buttons:
            button.draw(self.screen, self.font_small)

    def _phase_instruction(self, snapshot: dict[str, object]) -> str:
        phase = str(snapshot.get("phase"))
        prompt = snapshot.get("pending_prompt") or {}
        me = str(snapshot.get("self_player_id"))
        current = str(snapshot.get("current_player_id"))
        if isinstance(prompt, dict) and prompt.get("type") == "defend":
            return "Escolha com quantos dados defender. Empates favorecem o defensor."
        if isinstance(prompt, dict) and prompt.get("type") == "capture_move":
            return "Após conquistar, confirme quantas tropas vão ocupar o território."
        if current and me != current and phase not in {"lobby", "game_over"}:
            return f"Aguarde a ação de {self._player_name(snapshot, current)}."
        if phase == "setup":
            return "Clique em um território seu para posicionar 1 tropa de preparação."
        if phase == "reinforcement":
            return "Clique em territórios seus para distribuir todos os reforços."
        if phase == "attack":
            if me != current:
                return "Aguarde o outro jogador atacar ou encerrar a fase."
            return "Você pode fazer vários ataques nesta fase. Selecione origem e alvo; quando terminar, encerre o ataque."
        if phase == "fortify":
            return "Você pode fazer uma única manobra entre territórios seus conectados."
        if phase == "game_over":
            return "Partida encerrada. A missão vencedora foi cumprida."
        return "Acompanhe a situação da partida e consulte as regras quando precisar."

    def _bottom_bar_instruction(self, snapshot: dict[str, object]) -> str:
        phase = str(snapshot.get("phase"))
        me = str(snapshot.get("self_player_id"))
        current = str(snapshot.get("current_player_id"))
        if current and me != current and phase not in {"lobby", "game_over"}:
            return f"Aguarde a ação de {self._player_name(snapshot, current)}. Você verá a atualização assim que o outro jogador agir."
        if phase == "attack":
            return "Ataques não são limitados a 1 por rodada. Continue atacando ou encerre a fase quando quiser parar."
        if phase == "fortify":
            return "Escolha dois territórios seus conectados para manobrar, ou encerre o turno."
        if phase == "reinforcement":
            return "Distribua reforços antes de atacar. Trocas de cartas aparecem aqui quando estiverem disponíveis."
        if phase == "setup":
            return "Preparação: posicione tropas extras nos seus territórios."
        return "Passe o mouse sobre o mapa para ver o território e suas tropas."

    def _draw_rules_modal(self) -> None:
        overlay = pygame.Surface(WINDOW_SIZE, pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))

        modal = pygame.Rect(210, 62, WINDOW_SIZE[0] - 420, WINDOW_SIZE[1] - 124)
        self._draw_panel(modal, PANEL)
        title_surface = self.font_big.render("Regras do Jogo", True, TEXT)
        self.screen.blit(title_surface, (modal.x + 24, modal.y + 18))
        subtitle = "Manual paginado para consultar durante a partida."
        self.screen.blit(self.font_small.render(subtitle, True, SUBTLE), (modal.x + 24, modal.y + 54))

        close_button = Button(pygame.Rect(modal.right - 120, modal.y + 20, 96, 34), "Fechar", ("close_rules", None))
        self.game_buttons.append(close_button)
        close_button.draw(self.screen, self.font_small)

        self.rules_page = max(0, min(self.rules_page, len(RULES_PAGES) - 1))
        page_title, items = RULES_PAGES[self.rules_page]
        content = pygame.Rect(modal.x + 34, modal.y + 104, modal.width - 68, modal.height - 190)
        self.screen.blit(self.font_big.render(page_title, True, TEXT), (content.x, content.y))
        pygame.draw.line(self.screen, ACCENT, (content.x, content.y + 42), (content.x + 110, content.y + 42), 3)

        cursor_y = content.y + 62
        for item in items:
            lines = wrap_text(item, self.font_small, content.width - 30, max_lines=4)
            pygame.draw.circle(self.screen, ACCENT, (content.x + 7, cursor_y + 8), 4)
            for line_index, line in enumerate(lines):
                self.screen.blit(self.font_small.render(line, True, TEXT), (content.x + 24, cursor_y + line_index * 18))
            cursor_y += len(lines) * 18 + 14

        page_label = f"Página {self.rules_page + 1} de {len(RULES_PAGES)}"
        self.screen.blit(self.font_small.render(page_label, True, SUBTLE), (modal.x + 34, modal.bottom - 54))
        prev_button = Button(
            pygame.Rect(modal.right - 310, modal.bottom - 62, 90, 36),
            "Anterior",
            ("rules_page", -1),
            self.rules_page > 0,
        )
        next_button = Button(
            pygame.Rect(modal.right - 208, modal.bottom - 62, 90, 36),
            "Próxima",
            ("rules_page", 1),
            self.rules_page < len(RULES_PAGES) - 1,
        )
        self.game_buttons.extend([prev_button, next_button])
        prev_button.draw(self.screen, self.font_small)
        next_button.draw(self.screen, self.font_small)

    def _draw_hand(self, snapshot: dict[str, object], x: int, y: int, width: int) -> None:
        box = pygame.Rect(x, y, width, 196)
        self._draw_panel(box, PANEL_ALT)
        self._draw_section_header("Suas Cartas", x + 10, y + 8, width - 20)
        self.card_rects.clear()
        hand = list(snapshot.get("your_hand", []))
        if not hand:
            empty_text = "Você ainda não tem cartas. Conquiste um território e encerre o turno para receber 1 carta."
            for index, line in enumerate(wrap_text(empty_text, self.font_small, width - 20, max_lines=5)):
                self.screen.blit(self.font_small.render(line, True, SUBTLE), (x + 10, y + 42 + index * 18))
        for index, card in enumerate(hand[:6]):
            rect = pygame.Rect(x + 10, y + 36 + index * 24, width - 20, 22)
            self.card_rects[str(card["id"])] = rect
            selected = str(card["id"]) in self.selected_cards
            is_wild = str(card.get("kind")) == "wild"
            fill = (224, 208, 255) if is_wild else (246, 236, 198)
            if selected:
                fill = (255, 209, 102)
            pygame.draw.rect(self.screen, fill, rect, border_radius=8)
            pygame.draw.rect(self.screen, (80, 70, 50), rect, width=1, border_radius=8)
            territory_id = str(card.get("territory") or "wild")
            territory_name = self._territory_name(snapshot, territory_id)
            symbol = str(card["symbol"])
            glyph_rect = pygame.Rect(rect.x + 5, rect.y + 4, 18, 14)
            pygame.draw.rect(self.screen, (42, 38, 52) if is_wild else (255, 255, 255), glyph_rect, border_radius=5)
            glyph_color = (255, 255, 255) if is_wild else (30, 30, 35)
            glyph_surface = self.font_tiny.render(symbol_glyph(symbol), True, glyph_color)
            self.screen.blit(glyph_surface, glyph_surface.get_rect(center=glyph_rect.center))
            symbol_label = CARD_SYMBOL_LABELS.get(symbol, symbol)
            text = fit_text(f"{territory_name} | {symbol_label}", self.font_tiny, rect.width - 34)
            self.screen.blit(self.font_tiny.render(text, True, (30, 30, 35)), (rect.x + 28, rect.y + 5))
        trade_sets = list(snapshot.get("your_trade_sets", []))
        mandatory = bool(snapshot.get("must_trade"))
        footer = "Troca obrigatória" if mandatory else f"Conjuntos de troca disponíveis: {len(trade_sets)}"
        footer = fit_text(footer, self.font_small, width - 20)
        self.screen.blit(self.font_small.render(footer, True, TEXT if mandatory else SUBTLE), (x + 10, y + 176))

    def _draw_log(self, snapshot: dict[str, object], x: int, y: int, width: int, height: int) -> None:
        box = pygame.Rect(x, y, width, max(60, height))
        self._draw_panel(box, PANEL_ALT)
        self._draw_section_header("Batalha / Registro", x + 10, y + 8, width - 20)
        battle = snapshot.get("last_battle") or {}
        cursor_y = y + 38
        if isinstance(battle, dict) and battle:
            cursor_y = self._draw_battle_dice(battle, x + 10, cursor_y, width - 20)
        max_lines = max(2, (box.bottom - cursor_y - 8) // 18)
        for line in list(snapshot.get("log", []))[-max_lines:]:
            rendered = self.font_small.render(fit_text(str(line), self.font_small, width - 20), True, SUBTLE)
            self.screen.blit(rendered, (x + 10, cursor_y))
            cursor_y += 18

    def _draw_battle_dice(self, battle: dict[str, object], x: int, y: int, width: int) -> int:
        title = fit_text(f"{battle.get('attacker')} atacou {battle.get('defender')}", self.font_small, width)
        self.screen.blit(self.font_small.render(title, True, TEXT), (x, y))
        y += 20
        y = self._draw_dice_row("Ataque", list(battle.get("attacker_rolls", [])), (209, 70, 70), x, y, width)
        y = self._draw_dice_row("Defesa", list(battle.get("defender_rolls", [])), (78, 137, 225), x, y, width)
        losses = f"Perdas: atacante {battle.get('attacker_losses', 0)} | defensor {battle.get('defender_losses', 0)}"
        self.screen.blit(self.font_tiny.render(fit_text(losses, self.font_tiny, width), True, SUBTLE), (x, y + 2))
        return y + 20

    def _draw_dice_row(
        self,
        label: str,
        rolls: list[object],
        color: tuple[int, int, int],
        x: int,
        y: int,
        width: int,
    ) -> int:
        self.screen.blit(self.font_tiny.render(label, True, SUBTLE), (x, y + 4))
        dice_x = x + 58
        for roll in rolls[:3]:
            if dice_x + 24 > x + width:
                break
            self._draw_die(pygame.Rect(dice_x, y, 22, 22), int(roll), color)
            dice_x += 28
        return y + 28

    def _draw_die(self, rect: pygame.Rect, value: int, color: tuple[int, int, int]) -> None:
        pygame.draw.rect(self.screen, color, rect, border_radius=5)
        pygame.draw.rect(self.screen, (245, 245, 245), rect, width=1, border_radius=5)
        pip_positions = {
            1: [(0.5, 0.5)],
            2: [(0.28, 0.28), (0.72, 0.72)],
            3: [(0.28, 0.28), (0.5, 0.5), (0.72, 0.72)],
            4: [(0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)],
            5: [(0.28, 0.28), (0.72, 0.28), (0.5, 0.5), (0.28, 0.72), (0.72, 0.72)],
            6: [(0.28, 0.24), (0.72, 0.24), (0.28, 0.5), (0.72, 0.5), (0.28, 0.76), (0.72, 0.76)],
        }
        for rel_x, rel_y in pip_positions.get(max(1, min(6, value)), []):
            pygame.draw.circle(
                self.screen,
                (255, 255, 255),
                (int(rect.x + rect.width * rel_x), int(rect.y + rect.height * rel_y)),
                2,
            )

    def _build_game_buttons(self, snapshot: dict[str, object], x: int, y: int, width: int) -> list[Button]:
        buttons: list[Button] = []
        cursor_x = x

        def add_button(label: str, button_width: int, action: tuple[str, object | None], enabled: bool = True) -> None:
            nonlocal cursor_x
            remaining_width = x + width - cursor_x
            if remaining_width < 36:
                return
            actual_width = min(button_width, remaining_width)
            buttons.append(Button(pygame.Rect(cursor_x, y, actual_width, 34), label, action, enabled))
            cursor_x += actual_width + 10

        prompt = snapshot.get("pending_prompt") or {}
        phase = str(snapshot.get("phase"))
        me = str(snapshot.get("self_player_id"))
        current = str(snapshot.get("current_player_id"))
        is_my_turn = me == current and phase != "game_over"
        if isinstance(prompt, dict) and prompt.get("type") == "defend":
            max_dice = int(prompt.get("max_defense_dice", 1))
            for index in range(1, max_dice + 1):
                add_button(f"Defender {index}", 118, ("defend", index))
            return buttons
        if isinstance(prompt, dict) and prompt.get("type") == "capture_move":
            add_button("-", 44, ("move_delta", -1))
            add_button("+", 44, ("move_delta", 1))
            add_button("Mover Tropas", 142, ("capture_move", None))
            return buttons
        if not is_my_turn:
            return buttons
        if phase == "reinforcement":
            if len(self.selected_cards) == 3:
                add_button("Trocar Selecionadas", 190, ("trade_selected", None))
            elif snapshot.get("your_trade_sets"):
                add_button("Troca Automática", 170, ("auto_trade", None))
            return buttons
        if phase == "attack":
            pair = self._selected_attack_pair(snapshot)
            if pair:
                source = self._territory(snapshot, pair[0])
                max_attack = min(3, int(source["troops"]) - 1)
                for dice in range(1, max_attack + 1):
                    add_button(f"Atacar {dice}", 88, ("attack", dice))
            add_button("Encerrar Ataque", 150, ("end_attack_phase", None))
            add_button("Encerrar Turno", 142, ("end_turn", None))
            return buttons
        if phase == "fortify":
            pair = self._selected_fortify_pair(snapshot)
            if pair:
                source = self._territory(snapshot, pair[0])
                max_move = max(1, int(source["troops"]) - 1)
                self.move_count = max(1, min(max_move, self.move_count or 1))
                add_button("-", 44, ("move_delta", -1))
                add_button("+", 44, ("move_delta", 1))
                add_button("Manobrar", 124, ("fortify", None))
            add_button("Encerrar Turno", 142, ("end_turn", None))
        return buttons

    def _handle_game_click(self, pos: tuple[int, int]) -> bool:
        for button in self.game_buttons:
            if button.enabled and button.rect.collidepoint(pos):
                self._activate(button.action)
                return True
        for card_id, rect in self.card_rects.items():
            if rect.collidepoint(pos):
                if card_id in self.selected_cards:
                    self.selected_cards.remove(card_id)
                else:
                    if len(self.selected_cards) >= 3:
                        self.selected_cards = {card_id}
                    else:
                        self.selected_cards.add(card_id)
                return True
        return False

    def _handle_territory_click(self, territory_id: str) -> None:
        if not self.snapshot or not self.client:
            return
        phase = str(self.snapshot.get("phase"))
        me = str(self.snapshot.get("self_player_id"))
        current = str(self.snapshot.get("current_player_id"))
        prompt = self.snapshot.get("pending_prompt") or {}
        if isinstance(prompt, dict) and prompt:
            return
        territory = self._territory(self.snapshot, territory_id)
        if phase == "setup" and me == current and territory.get("owner") == me:
            result = self.client.submit_action("place_setup_army", {"territory_id": territory_id})
            self._set_result_message(result, success="Tropa inicial posicionada.")
            return
        if phase == "reinforcement" and me == current and territory.get("owner") == me:
            result = self.client.submit_action(
                "place_reinforcements",
                {"territory_id": territory_id, "count": 1},
            )
            self._set_result_message(result, success="Reforço posicionado.")
            return
        if territory_id in self.selected_territories:
            self.selected_territories.remove(territory_id)
            return
        if len(self.selected_territories) >= 2:
            self.selected_territories = [territory_id]
        else:
            self.selected_territories.append(territory_id)

    def _board_rect(self) -> tuple[pygame.Rect, float]:
        available_height = WINDOW_SIZE[1] - 40
        scale = BOARD_RENDER_WIDTH / self.board_image.get_width()
        size = (BOARD_RENDER_WIDTH, int(self.board_image.get_height() * scale))
        rect = pygame.Rect(
            OUTER_MARGIN + LEFT_SIDEBAR_WIDTH + PANEL_GAP,
            20 + (available_height - size[1]) // 2,
            size[0],
            size[1],
        )
        return rect, scale

    def _scaled_board_image(self, size: tuple[int, int]) -> pygame.Surface:
        if size not in self.board_cache:
            self.board_cache[size] = pygame.transform.smoothscale(self.board_image, size)
        return self.board_cache[size]

    def _draw_board_overlays(self, board_rect: pygame.Rect, scale: float, snapshot: dict[str, object]) -> None:
        overlay = pygame.Surface(board_rect.size, pygame.SRCALPHA)
        hover_pos = self._virtual_mouse_pos()
        hover = self._territory_at_pos(hover_pos) if hover_pos else None
        selected = set(self.selected_territories)
        territory_map = {territory["territory_id"]: territory for territory in snapshot.get("territories", [])}
        for edge_a, edge_b in self.board_definition.special_edges():
            ta = self.board_definition.territories.get(edge_a)
            tb = self.board_definition.territories.get(edge_b)
            if not ta or not tb:
                continue
            start = self._scale_point_overlay((ta.label_x, ta.label_y), scale)
            end = self._scale_point_overlay((tb.label_x, tb.label_y), scale)
            draw_dashed_line(overlay, (255, 255, 255, 120), start, end, 2, 8)
        for territory_id in self.board_definition.territories_in_order:
            definition = self.board_definition.territories[territory_id]
            territory = territory_map.get(territory_id)
            if not territory:
                continue
            points = [self._scale_point_overlay((float(px), float(py)), scale) for px, py in definition.polygon]
            owner = territory.get("owner")
            color = PLAYER_COLORS.get(str(next((player.get("color") for player in snapshot.get("players", []) if player.get("player_id") == owner), "")), (180, 180, 180))
            fill = (*color, 65 if territory_id in selected or territory_id == hover else 28)
            pygame.draw.polygon(overlay, fill, points)
            border_color = TEXT if territory_id in selected else (*color, 190)
            pygame.draw.polygon(overlay, border_color, points, 2)
        self.screen.blit(overlay, board_rect.topleft)
        for territory_id in self.board_definition.territories_in_order:
            definition = self.board_definition.territories[territory_id]
            territory = territory_map.get(territory_id)
            if not territory:
                continue
            label_anchor = self._scale_point((definition.label_x, definition.label_y), board_rect, scale)
            bubble_center = (label_anchor[0], label_anchor[1] + 12)
            owner = territory.get("owner")
            color = PLAYER_COLORS.get(str(next((player.get("color") for player in snapshot.get("players", []) if player.get("player_id") == owner), "")), SUBTLE)
            pygame.draw.circle(self.screen, color, bubble_center, 17)
            pygame.draw.circle(self.screen, (25, 25, 30), bubble_center, 17, 2)
            troops = int(territory.get("troops", 0))
            troop_text = self.font_small.render(str(troops), True, (10, 10, 10))
            self.screen.blit(troop_text, troop_text.get_rect(center=bubble_center))
            self._draw_territory_label(board_rect, territory_id, str(territory["display_name"]), label_anchor)
    def _territory_at_pos(self, pos: tuple[int, int]) -> str | None:
        if not self.snapshot:
            return None
        board_rect, scale = self._board_rect()
        if not board_rect.collidepoint(pos):
            return None
        board_x = (pos[0] - board_rect.x) / scale
        board_y = (pos[1] - board_rect.y) / scale
        for territory_id in reversed(self.board_definition.territories_in_order):
            polygon = self.board_definition.territories[territory_id].polygon
            if point_in_polygon(board_x, board_y, polygon):
                return territory_id
        return None

    def _territory(self, snapshot: dict[str, object], territory_id: str) -> dict[str, object]:
        for territory in snapshot.get("territories", []):
            if territory["territory_id"] == territory_id:
                return territory
        raise KeyError(territory_id)

    def _self_player(self, snapshot: dict[str, object]) -> dict[str, object] | None:
        self_player_id = snapshot.get("self_player_id")
        for player in snapshot.get("players", []):
            if player.get("player_id") == self_player_id:
                return player
        return None

    def _player_name(self, snapshot: dict[str, object], player_id: str | None) -> str:
        for player in snapshot.get("players", []):
            if player.get("player_id") == player_id:
                return str(player.get("name", "outro jogador"))
        return "outro jogador"

    def _territory_name(self, snapshot: dict[str, object], territory_id: str) -> str:
        if territory_id == "wild":
            return "Curinga"
        return str(self._territory(snapshot, territory_id)["display_name"])

    def _selected_attack_pair(self, snapshot: dict[str, object]) -> tuple[str, str] | None:
        if len(self.selected_territories) != 2:
            return None
        me = str(snapshot.get("self_player_id"))
        source = self._territory(snapshot, self.selected_territories[0])
        target = self._territory(snapshot, self.selected_territories[1])
        if source.get("owner") == me and target.get("owner") not in {None, me} and self.selected_territories[1] in source.get("neighbors", []):
            return self.selected_territories[0], self.selected_territories[1]
        return None

    def _selected_fortify_pair(self, snapshot: dict[str, object]) -> tuple[str, str] | None:
        if len(self.selected_territories) != 2:
            return None
        me = str(snapshot.get("self_player_id"))
        source = self._territory(snapshot, self.selected_territories[0])
        target = self._territory(snapshot, self.selected_territories[1])
        if source.get("owner") == me and target.get("owner") == me and int(source.get("troops", 0)) > 1:
            return self.selected_territories[0], self.selected_territories[1]
        return None

    def _scale_point(self, point: tuple[float, float], board_rect: pygame.Rect, scale: float) -> tuple[int, int]:
        return int(board_rect.x + point[0] * scale), int(board_rect.y + point[1] * scale)

    def _scale_point_overlay(self, point: tuple[float, float], scale: float) -> tuple[int, int]:
        return int(point[0] * scale), int(point[1] * scale)

    def _calcular_viewport(self) -> pygame.Rect:
        escala = min(self.window_size[0] / WINDOW_SIZE[0], self.window_size[1] / WINDOW_SIZE[1])
        largura = max(1, int(WINDOW_SIZE[0] * escala))
        altura = max(1, int(WINDOW_SIZE[1] * escala))
        return pygame.Rect(
            (self.window_size[0] - largura) // 2,
            (self.window_size[1] - altura) // 2,
            largura,
            altura,
        )

    def _to_virtual_pos(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        if not self.viewport_rect.collidepoint(pos):
            return None
        rel_x = (pos[0] - self.viewport_rect.x) / self.viewport_rect.width
        rel_y = (pos[1] - self.viewport_rect.y) / self.viewport_rect.height
        return int(rel_x * WINDOW_SIZE[0]), int(rel_y * WINDOW_SIZE[1])

    def _virtual_mouse_pos(self) -> tuple[int, int] | None:
        return self._to_virtual_pos(pygame.mouse.get_pos())

    def _draw_territory_label(
        self,
        board_rect: pygame.Rect,
        territory_id: str,
        display_name: str,
        label_anchor: tuple[int, int],
    ) -> None:
        lines = wrap_text(display_name, self.font_tiny, 92, max_lines=2)
        max_width = max(self.font_tiny.size(line)[0] for line in lines)
        pill_rect = pygame.Rect(0, 0, max_width + 12, len(lines) * 12 + 8)
        pill_rect.centerx = label_anchor[0]
        pill_rect.centery = label_anchor[1] - 12
        pill_rect.clamp_ip(board_rect.inflate(-8, -8))
        pygame.draw.rect(self.screen, (15, 17, 22), pill_rect, border_radius=8)
        pygame.draw.rect(self.screen, (210, 214, 222), pill_rect, width=1, border_radius=8)
        for index, line in enumerate(lines):
            text_surface = self.font_tiny.render(line, True, TEXT)
            line_rect = text_surface.get_rect(center=(pill_rect.centerx, pill_rect.y + 10 + index * 12))
            self.screen.blit(text_surface, line_rect)

    def _draw_panel(self, rect: pygame.Rect, color: tuple[int, int, int] = PANEL) -> None:
        pygame.draw.rect(self.screen, color, rect, border_radius=14)
        pygame.draw.rect(self.screen, (60, 67, 78), rect, width=1, border_radius=14)

    def _draw_section_header(self, title: str, x: int, y: int, width: int) -> int:
        title_surface = self.font.render(title, True, TEXT)
        self.screen.blit(title_surface, (x, y))
        line_y = y + title_surface.get_height() + 4
        accent_end = x + min(58, width)
        pygame.draw.line(self.screen, ACCENT, (x, line_y), (accent_end, line_y), 3)
        if accent_end + 8 < x + width:
            pygame.draw.line(self.screen, (60, 67, 78), (accent_end + 8, line_y), (x + width, line_y), 1)
        return line_y + 8

    def _draw_message(self, x: int, y: int, width: int, max_lines: int | None = None) -> None:
        for index, line in enumerate(wrap_text(self.message, self.font_small, width, max_lines=max_lines)):
            self.screen.blit(self.font_small.render(line, True, self.message_color), (x, y + index * 16))

    def _set_message(self, message: str, color: tuple[int, int, int]) -> None:
        self.message = message
        self.message_color = color

    def _set_result_message(self, result: dict[str, object], success: str | None = None) -> None:
        if result.get("ok"):
            self._set_message(success or "Ação concluída.", SUCCESS)
        else:
            self._set_message(str(result.get("error", "Erro desconhecido.")), ERROR)

    def _shutdown(self) -> None:
        if self.client:
            self.client.disconnect()
        if self.server_process:
            self.server_process.terminate()
        pygame.quit()


def fit_text(text: str, font: pygame.font.Font, max_width: int) -> str:
    if font.size(text)[0] <= max_width:
        return text
    suffix = "..."
    clipped = text
    while clipped and font.size(clipped + suffix)[0] > max_width:
        clipped = clipped[:-1]
    return (clipped.rstrip() + suffix) if clipped else suffix


def wrap_text(
    text: str,
    font: pygame.font.Font,
    max_width: int,
    max_lines: int | None = None,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = fit_text(words[0], font, max_width)
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.size(candidate)[0] <= max_width:
            current = candidate
            continue
        lines.append(current)
        if max_lines is not None and len(lines) >= max_lines:
            lines[-1] = fit_text(f"{lines[-1]} ...", font, max_width)
            return lines
        current = fit_text(word, font, max_width)
    lines.append(current)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
    if max_lines is not None and len(words) > 0 and len(lines) == max_lines:
        remaining_text = " ".join(words)
        rebuilt = " ".join(lines)
        if rebuilt != remaining_text:
            lines[-1] = fit_text(f"{lines[-1]} ...", font, max_width)
    return lines


def symbol_glyph(symbol: str) -> str:
    return {
        "infantry": "I",
        "cavalry": "C",
        "artillery": "A",
        "wild": "*",
    }.get(symbol, "?")


def draw_dashed_line(
    surface: pygame.Surface,
    color: tuple[int, int, int, int],
    start: tuple[int, int],
    end: tuple[int, int],
    width: int,
    dash_length: int,
) -> None:
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    distance = max(1, int((dx * dx + dy * dy) ** 0.5))
    for offset in range(0, distance, dash_length * 2):
        start_ratio = offset / distance
        end_ratio = min(distance, offset + dash_length) / distance
        seg_start = (int(x1 + dx * start_ratio), int(y1 + dy * start_ratio))
        seg_end = (int(x1 + dx * end_ratio), int(y1 + dy * end_ratio))
        pygame.draw.line(surface, color, seg_start, seg_end, width)


def escolher_porta_local_livre(porta_preferida: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", porta_preferida))
            return porta_preferida
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])


def main(configuracao: ConfiguracaoCliente | None = None) -> None:
    app = RiskClientApp(configuracao)
    app.run()


def calcular_tamanho_janela() -> tuple[int, int]:
    info = pygame.display.Info()
    return max(640, int(info.current_w * WINDOW_RATIO)), max(360, int(info.current_h * WINDOW_RATIO))
