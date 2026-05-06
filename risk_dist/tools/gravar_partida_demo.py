"""Gera um GIF automático demonstrando uma partida até a vitória."""

from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
from PIL import Image

from risk_dist.client.network import RpcGameClient, endpoint_from_host_port
from risk_dist.client.ui import ConfiguracaoCliente, RiskClientApp, WINDOW_SIZE
from risk_dist.server.network import GameRpcService, create_rpc_server
from risk_dist.shared.rules import mission_by_id


DEFAULT_OUTPUT = Path("risk_dist/demo_partida.gif")


def gravar_demo(saida: Path = DEFAULT_OUTPUT, rapido: bool = False) -> Path:
    service = GameRpcService()
    server = create_rpc_server("127.0.0.1", 0, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    endpoint = endpoint_from_host_port(str(host), int(port))

    alice = RpcGameClient(endpoint)
    bob = RpcGameClient(endpoint)
    app = RiskClientApp(ConfiguracaoCliente(nome_inicial="Alice", servidor_inicial=f"{host}:{port}"))
    app.message = "Demonstração automática: jogo distribuído com 1 servidor e 2 clientes RPC."

    frames: list[Image.Image] = []
    repeats = 1 if rapido else 4
    scale = 0.45 if rapido else 0.62

    def capture(repeticoes: int | None = None) -> None:
        app._draw()
        image = _surface_to_image(app.screen, scale)
        for _ in range(repeticoes if repeticoes is not None else repeats):
            frames.append(image.copy())

    def sync(client: RpcGameClient = alice, mensagem: str | None = None) -> dict[str, object]:
        result = client.poll_snapshot(None)
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeError(f"Snapshot inválido: {result!r}")
        app.client = alice
        app.snapshot = snapshot
        app.snapshot_version = int(result["version"])
        app._ingest_snapshot(snapshot)
        if mensagem:
            app._set_message(mensagem, (93, 204, 123))
        return snapshot

    def finish_setup() -> None:
        safety = 0
        while service.game.phase == "setup" and safety < 90:
            current = service.game.current_player_id
            if not current:
                break
            territory_id = next(
                territory_id
                for territory_id, state in service.game.territories.items()
                if state["owner"] == current
            )
            client = alice if current == alice.player_id else bob
            client.submit_action("place_setup_army", {"territory_id": territory_id})
            safety += 1

    def prepare_demo_state(source: str, target: str, alice_count: int, card_ready: bool) -> None:
        board = service.game.board
        alice_owned = {
            "alaska",
            "northwest_territory",
            "greenland",
            "alberta",
            "ontario",
            "quebec",
            "western_united_states",
            "eastern_united_states",
            "central_america",
            "venezuela",
            "iceland",
            "great_britain",
            "scandinavia",
            "northern_europe",
            "western_europe",
            "southern_europe",
            "ukraine",
            "north_africa",
            "egypt",
            "east_africa",
            "congo",
            "south_africa",
        }
        if alice_count >= 23:
            alice_owned.add("brazil")
        for territory_id in board.territories_in_order:
            service.game.territories[territory_id]["owner"] = bob.player_id
            service.game.territories[territory_id]["troops"] = 2
        for territory_id in alice_owned:
            service.game.territories[territory_id]["owner"] = alice.player_id
            service.game.territories[territory_id]["troops"] = 2
        service.game.territories[source]["owner"] = alice.player_id
        service.game.territories[source]["troops"] = 30
        service.game.territories[target]["owner"] = bob.player_id
        service.game.territories[target]["troops"] = 1
        service.game.players[alice.player_id].mission = mission_by_id("occupy_24")
        service.game.players[bob.player_id].mission = mission_by_id("occupy_18_with_2")
        service.game.players[alice.player_id].reinforcements_to_place = 0
        service.game.players[bob.player_id].reinforcements_to_place = 0
        service.game.current_player_id = alice.player_id
        service.game.phase = "attack"
        service.game.pending_prompt = None
        service.game.pending_battle = None
        service.game.last_battle = None
        service.game.turn_conquest_happened = False
        service.game.turn_card_awarded = False
        service.game.draw_deck = [
            {"id": "demo_alaska", "territory": "alaska", "symbol": "infantry", "kind": "territory"},
            {"id": "demo_curinga", "territory": None, "symbol": "wild", "kind": "wild"},
        ]
        if not card_ready:
            service.game.players[alice.player_id].hand.clear()
        service.game._set_status("Demonstração: Alice pode atacar para conquistar território.")
        service.game._bump_version()

    def attack_until_capture(source: str, target: str) -> None:
        app.selected_territories = [source, target]
        sync(mensagem="Ataque selecionado: escolha a quantidade de dados na barra inferior.")
        capture()
        for _ in range(8):
            alice.submit_action("attack", {"from": source, "to": target, "dice": 3})
            sync(mensagem="Ataque enviado. O outro cliente precisa defender.")
            capture()
            bob.submit_action("defend", {"dice": 1})
            snapshot = sync(mensagem="Dados do ataque e da defesa aparecem no painel de batalha.")
            capture(2 if rapido else 5)
            prompt = snapshot.get("pending_prompt") or {}
            if isinstance(prompt, dict) and prompt.get("type") == "capture_move":
                alice.submit_action("capture_move", {"count": int(prompt["min_troops"])})
                sync(mensagem="Território conquistado. Tropas movidas para a conquista.")
                capture()
                return
        raise RuntimeError("A demonstração não conseguiu conquistar o território no limite esperado.")

    try:
        capture()
        alice.connect("Alice")
        app.client = alice
        sync(mensagem="Alice conectada ao servidor XML-RPC.")
        capture()
        bob.connect("Bob")
        sync(mensagem="Bob conectado: dois clientes coexistem no mesmo servidor.")
        capture()
        alice.choose_color("red")
        bob.choose_color("blue")
        alice.ready()
        bob.ready()
        sync(mensagem="Cores escolhidas e jogadores prontos. A partida iniciou.")
        capture()
        finish_setup()
        sync(mensagem="Preparação concluída. Agora entram os reforços e ataques.")
        capture()

        app.rules_visible = True
        app.rules_page = 3
        capture()
        app.rules_page = 4
        capture()
        app.rules_visible = False

        prepare_demo_state("venezuela", "brazil", alice_count=22, card_ready=False)
        sync(mensagem="Alice ainda não tem cartas antes de conquistar.")
        capture()
        attack_until_capture("venezuela", "brazil")
        alice.submit_action("end_turn", {})
        sync(mensagem="Alice conquistou território e recebeu 1 carta ao encerrar o turno.")
        capture(2 if rapido else 6)

        prepare_demo_state("brazil", "peru", alice_count=23, card_ready=True)
        sync(mensagem="Cenário final: Alice está a uma conquista de completar a missão.")
        capture()
        attack_until_capture("brazil", "peru")
        sync(mensagem="Missão cumprida. A partida terminou com vitória de Alice.")
        capture(3 if rapido else 8)

        saida = Path(saida)
        saida.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            saida,
            save_all=True,
            append_images=frames[1:],
            duration=450 if rapido else 700,
            loop=0,
            optimize=True,
        )
        return saida
    finally:
        app._shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _surface_to_image(surface: pygame.Surface, scale: float) -> Image.Image:
    raw = pygame.image.tostring(surface, "RGB")
    image = Image.frombytes("RGB", WINDOW_SIZE, raw)
    if scale != 1:
        image = image.resize((int(WINDOW_SIZE[0] * scale), int(WINDOW_SIZE[1] * scale)), Image.Resampling.LANCZOS)
    return image


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grava um GIF automático de uma partida demonstrativa.")
    parser.add_argument("--saida", default=str(DEFAULT_OUTPUT), help="Arquivo GIF de saída.")
    parser.add_argument("--rapido", action="store_true", help="Gera menos frames, útil para testes automatizados.")
    return parser


def main() -> None:
    args = montar_parser().parse_args()
    output = gravar_demo(Path(args.saida), rapido=bool(args.rapido))
    print(f"GIF gerado em: {output}")


if __name__ == "__main__":
    main()
