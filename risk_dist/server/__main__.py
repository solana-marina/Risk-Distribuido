"""Executa o servidor XML-RPC do Risk distribuído."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from risk_dist.server.network import serve_forever
from risk_dist.shared.constants import DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa o servidor distribuído de Risk.")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP para escuta.")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="Porta TCP para escuta.")
    args = parser.parse_args()
    serve_forever(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
