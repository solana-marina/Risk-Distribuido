"""Compatibilidade para código antigo que importava a camada de serviço.

A comunicação de rede do servidor foi movida para ``risk_dist.server.network``.
Este arquivo fica pequeno de propósito: se alguém ainda importar
``risk_dist.server.service``, o programa continua funcionando, mas o arquivo
didático para explicar RPC/RMI ao professor agora é ``server/network.py``.
"""

from __future__ import annotations

from risk_dist.server.network import (
    GameRpcService,
    GameService,
    RequestHandler,
    ThreadingXMLRPCServer,
    create_rpc_server,
    serve_forever,
)

__all__ = [
    "GameRpcService",
    "GameService",
    "RequestHandler",
    "ThreadingXMLRPCServer",
    "create_rpc_server",
    "serve_forever",
]
