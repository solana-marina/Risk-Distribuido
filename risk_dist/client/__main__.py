"""Executa o cliente pygame."""

from __future__ import annotations

import argparse

from risk_dist.client.ui import ConfiguracaoCliente, main


def _parse_args() -> ConfiguracaoCliente:
    parser = argparse.ArgumentParser(description="Executa o cliente de Risk em pygame.")
    parser.add_argument("--nome", default="Jogador", help="Nome inicial do jogador.")
    parser.add_argument("--servidor", default="", help="Servidor no formato IP:porta.")
    parser.add_argument("--autoconectar", action="store_true", help="Conecta automaticamente ao abrir.")
    parser.add_argument("--cor", default="", help="Cor preferida para escolher automaticamente no lobby.")
    parser.add_argument("--pronto", action="store_true", help="Marca o jogador como pronto automaticamente.")
    parser.add_argument("--x", type=int, help="Posição X inicial da janela.")
    parser.add_argument("--y", type=int, help="Posição Y inicial da janela.")
    args = parser.parse_args()
    posicao = None
    if args.x is not None and args.y is not None:
        posicao = (args.x, args.y)
    return ConfiguracaoCliente(
        nome_inicial=args.nome,
        servidor_inicial=args.servidor,
        autoconectar=args.autoconectar,
        cor_automatica=args.cor or None,
        pronto_automatico=args.pronto,
        posicao_janela=posicao,
    )


if __name__ == "__main__":
    main(_parse_args())
