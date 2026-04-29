"""Abre uma partida local com 1 servidor e 2 clientes."""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from risk_dist.client.network import rpc_server_responding
from risk_dist.shared.constants import DEFAULT_PORT


def escolher_porta_livre(host: str, porta_preferida: int) -> tuple[int, bool]:
    """Retorna uma porta livre para abrir um servidor local novo."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, porta_preferida))
            return porta_preferida, False
        except OSError:
            probe.bind((host, 0))
            return int(probe.getsockname()[1]), True


def esperar_servidor(
    endereco: str,
    processo: subprocess.Popen[bytes] | None = None,
    timeout_segundos: float = 10.0,
) -> None:
    """Espera até que o servidor XML-RPC responda."""
    inicio = time.time()
    while time.time() - inicio < timeout_segundos:
        if processo is not None and processo.poll() is not None:
            raise RuntimeError("O processo do servidor foi encerrado antes de aceitar conexões.")
        if rpc_server_responding(endereco):
            return
        time.sleep(0.2)
    raise RuntimeError("O servidor não respondeu dentro do tempo esperado.")


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Abre 1 servidor e 2 clientes locais para testar visualmente.")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor local.")
    parser.add_argument("--porta", default=DEFAULT_PORT, type=int, help="Porta do servidor local.")
    parser.add_argument("--jogador-1", default="Jogador 1", help="Nome do primeiro cliente.")
    parser.add_argument("--jogador-2", default="Jogador 2", help="Nome do segundo cliente.")
    parser.add_argument("--cor-1", default="red", help="Cor automática do primeiro cliente.")
    parser.add_argument("--cor-2", default="blue", help="Cor automática do segundo cliente.")
    parser.add_argument("--encerrar-apos", type=float, default=0.0, help="Fecha tudo automaticamente após N segundos.")
    return parser


def main() -> None:
    args = montar_parser().parse_args()
    raiz_projeto = Path(__file__).resolve().parents[2]
    porta, porta_substituida = escolher_porta_livre(args.host, int(args.porta))
    endereco = f"http://{args.host}:{porta}/RPC2"
    criacao_servidor = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    servidor = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "risk_dist.server",
            "--host",
            args.host,
            "--port",
            str(porta),
        ],
        cwd=raiz_projeto,
        creationflags=criacao_servidor,
    )

    clientes: list[subprocess.Popen[bytes]] = []
    try:
        esperar_servidor(endereco, processo=servidor)
        if porta_substituida:
            print(f"Porta {args.porta} ocupada; usando a porta livre {porta}.")
        print(f"Servidor iniciado em {args.host}:{porta}")

        configuracoes = (
            (args.jogador_1, args.cor_1, (40, 40)),
            (args.jogador_2, args.cor_2, (140, 90)),
        )
        for nome, cor, (pos_x, pos_y) in configuracoes:
            processo = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "risk_dist.client",
                    "--nome",
                    nome,
                    "--servidor",
                    f"{args.host}:{porta}",
                    "--autoconectar",
                    "--cor",
                    cor,
                    "--pronto",
                    "--x",
                    str(pos_x),
                    "--y",
                    str(pos_y),
                ],
                cwd=raiz_projeto,
            )
            clientes.append(processo)
            print(f"Cliente aberto: {nome} ({cor})")

        if args.encerrar_apos > 0:
            time.sleep(args.encerrar_apos)
        else:
            for cliente in clientes:
                cliente.wait()
    finally:
        for cliente in clientes:
            if cliente.poll() is None:
                cliente.terminate()
        if servidor.poll() is None:
            servidor.terminate()


if __name__ == "__main__":
    main()
