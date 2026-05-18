"""Rede do servidor no Risk distribuído.

Este módulo pega o ``RiskGame`` local e publica uma fachada XML-RPC para os
clientes. Tudo que abre porta TCP, registra métodos remotos ou recebe chamadas
pela rede fica concentrado aqui.

Na apresentação, vale destacar que o servidor é autoritativo: os clientes apenas
pedem ações, e o servidor valida, atualiza o estado oficial da partida e devolve
uma resposta. Para o cliente, chamar ``ready`` parece uma função normal; na
prática, a chamada atravessa TCP, HTTP e XML-RPC até chegar neste processo.

Em comparação com Java RMI, ``GameRpcService`` faz o papel do objeto remoto, e o
``ThreadingXMLRPCServer`` faz a parte de transporte que o runtime do RMI costuma
esconder. Registrar a instância no servidor é o equivalente didático de publicar
um objeto para que clientes remotos possam chamá-lo.
"""

from __future__ import annotations

import socket
from socketserver import ThreadingMixIn
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from risk_dist.server.game import RiskGame
from risk_dist.shared.constants import DEFAULT_PORT


class RequestHandler(SimpleXMLRPCRequestHandler):
    """Aceita chamadas XML-RPC apenas no caminho usado pelo cliente.

    A biblioteca padrão do Python usa ``/RPC2`` por convenção. Neste projeto, o
    endereço remoto completo é a combinação de host, porta e esse caminho.
    """

    rpc_paths = ("/RPC2",)


class ThreadingXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    """Servidor XML-RPC que atende cada requisição em uma thread.

    Isso permite que dois clientes chamem o servidor ao mesmo tempo. Como as
    requisições podem chegar em paralelo, o estado compartilhado fica protegido
    dentro de ``RiskGame``.
    """

    daemon_threads = True


class GameRpcService:
    """Fachada remota publicada para os clientes.

    A classe não implementa regras do Risk. Ela só define o que pode ser chamado
    pela rede e repassa tudo para ``RiskGame``, que continua sendo o dono do
    estado oficial da partida.

    Em Java RMI, esta classe seria parecida com uma implementação de
    ``RiskRemote``. Aqui não existe interface remota explícita; o XML-RPC expõe
    os métodos públicos registrados no servidor.
    """

    def __init__(self) -> None:
        self.game = RiskGame()

    def join_game(self, name: str) -> dict[str, object]:
        """Registra um novo jogador e devolve seu identificador de sessão."""
        return self.game.join_game(name)

    def choose_color(self, player_id: str, color: str) -> dict[str, object]:
        """Recebe a escolha de cor de um jogador no lobby."""
        return self.game.choose_color(player_id, color)

    def ready(self, player_id: str) -> dict[str, object]:
        """Marca um jogador como pronto para iniciar a partida."""
        return self.game.ready(player_id)

    def get_snapshot(
        self,
        player_id: str,
        last_version: int | None,
    ) -> dict[str, object]:
        """Retorna uma cópia do estado que este jogador pode enxergar.

        O snapshot é personalizado: missão secreta e cartas só aparecem para o
        dono. Assim, o servidor controla também o que cada cliente tem permissão
        de saber.
        """
        return self.game.get_snapshot(player_id, last_version)

    def submit_action(
        self,
        player_id: str,
        action: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Recebe uma jogada e deixa o servidor validar antes de aplicar.

        O cliente não decide se a ação é legal. Isso evita que processos
        diferentes mantenham versões diferentes da partida.
        """
        return self.game.submit_action(player_id, action, payload)

    def leave_game(self, player_id: str) -> dict[str, object]:
        """Remove ou marca como derrotado o jogador que saiu da partida."""
        return self.game.leave_game(player_id)


def create_rpc_server(
    host: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
    service: GameRpcService | None = None,
) -> ThreadingXMLRPCServer:
    """Cria o servidor XML-RPC e registra o objeto remoto.

    A função só prepara o servidor; quem chama decide quando iniciar o loop. Isso
    facilita os testes, porque eles podem criar uma instância em uma porta
    temporária, rodar em uma thread e encerrar no final.
    """
    server = ThreadingXMLRPCServer(
        (host, port),
        requestHandler=RequestHandler,
        allow_none=True,
        logRequests=False,
    )
    server.register_introspection_functions()
    server.register_instance(service or GameRpcService())
    return server


def serve_forever(host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
    """Inicia o servidor e fica aceitando chamadas até o processo encerrar.

    A partir daqui, outros processos na rede local conseguem chamar os métodos
    publicados por ``GameRpcService``.
    """
    with create_rpc_server(host, port) as server:
        print(f"Servidor de Risk ouvindo em {host}:{port}")
        if host == "0.0.0.0":
            print(f"No mesmo computador, conecte o cliente em: 127.0.0.1:{port}")
            addresses = local_ipv4_addresses()
            if addresses:
                print("Em outro computador na mesma rede, use um destes IPs do servidor:")
                for address in addresses:
                    print(f"  {address}:{port}")
            else:
                print("Em outro computador, descubra o IPv4 do servidor com: ipconfig")
            print(
                "Observação: 0.0.0.0 é endereço de escuta do servidor; "
                "o cliente não deve usar esse endereço."
            )
        server.serve_forever()


def local_ipv4_addresses() -> list[str]:
    """Lista IPs locais que podem ser usados por clientes na mesma rede.

    O servidor pode escutar em ``0.0.0.0``, mas o cliente precisa apontar para um
    IP real da máquina, como ``192.168.x.x`` ou ``10.x.x.x``.
    """
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)
