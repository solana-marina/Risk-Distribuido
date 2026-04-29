"""Camada servidor de rede do Risk distribuído.

Este arquivo concentra tudo que transforma o jogo local ``RiskGame`` em um
serviço remoto acessível pelos clientes pygame. A regra didática é simples:
todo código que abre porta TCP, registra métodos remotos ou recebe chamadas de
rede fica aqui.

Relação com sistemas distribuídos:
- O servidor é autoritativo: só ele altera o estado oficial da partida.
- Os clientes enviam chamadas remotas pedindo ações.
- O servidor valida cada ação, atualiza o estado e devolve um resultado.
- XML-RPC implementa chamada de procedimento remoto usando HTTP e XML.
- Para cada cliente, chamar ``ready`` parece chamar uma função comum; na
  verdade, a chamada atravessa a rede e executa neste processo servidor.

Paralelo com Java RMI:
- ``GameRpcService`` faz o papel do objeto remoto que implementaria uma
  interface como ``RiskRemote extends Remote``.
- ``ThreadingXMLRPCServer`` faz o papel de infraestrutura de transporte, algo
  que em RMI fica escondido atrás do runtime, do registry e dos stubs.
- ``server.register_instance(service)`` lembra registrar/publicar um objeto
  remoto para que clientes possam chamá-lo.
"""

from __future__ import annotations

from socketserver import ThreadingMixIn
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from risk_dist.server.game import RiskGame
from risk_dist.shared.constants import DEFAULT_PORT


class RequestHandler(SimpleXMLRPCRequestHandler):
    """Define quais caminhos HTTP aceitam chamadas XML-RPC.

    A biblioteca padrão do Python usa ``/RPC2`` como caminho convencional. Se o
    cliente chamar outro caminho, o servidor não trata como chamada RPC.

    Paralelo com Java:
    - Em RMI, o cliente localiza o objeto remoto pelo registry.
    - Aqui, a localização é a combinação ``host + porta + /RPC2``.
    """

    rpc_paths = ("/RPC2",)


class ThreadingXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    """Servidor XML-RPC com uma thread por requisição.

    O trabalho exige pelo menos dois clientes coexistindo. Usar threads permite
    que o servidor aceite chamadas dos dois clientes sem bloquear todo mundo em
    uma única conexão. O estado compartilhado continua protegido dentro de
    ``RiskGame`` por ``threading.RLock``.

    Paralelo com Java:
    - RMI também pode atender chamadas remotas concorrentes em múltiplas
      threads.
    - Por isso, tanto em Java quanto aqui, o objeto remoto precisa proteger o
      estado compartilhado.
    """

    daemon_threads = True


class GameRpcService:
    """Objeto remoto publicado pelo servidor.

    Esta classe é uma fachada fina sobre ``RiskGame``. Ela não contém regras do
    Risk; ela só define quais métodos podem ser chamados pela rede e encaminha
    essas chamadas ao motor autoritativo.

    Conceito distribuído importante:
    - O cliente nunca recebe uma referência direta para ``RiskGame``.
    - O cliente só chama os métodos expostos aqui.
    - Isso cria uma fronteira clara entre apresentação, rede e regras.

    Paralelo com Java:
    - Em Java, esta classe seria parecida com ``RiskRemoteImpl``.
    - Os métodos abaixo seriam declarados também em uma interface remota, como
      ``RiskRemote``.
    - Cada método precisaria declarar ``throws RemoteException`` em Java; aqui
      falhas de transporte aparecem como exceções XML-RPC no cliente.
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

    def get_snapshot(self, player_id: str, last_version: int | None) -> dict[str, object]:
        """Retorna o estado visível ao jogador quando houver atualização.

        O snapshot é personalizado: missão secreta e mão de cartas só aparecem
        para o dono. Esse é um ponto importante em sistemas distribuídos de
        jogos: o servidor controla qual parte do estado cada cliente pode ver.
        """
        return self.game.get_snapshot(player_id, last_version)

    def submit_action(self, player_id: str, action: str, payload: dict[str, object]) -> dict[str, object]:
        """Recebe uma intenção de jogada e deixa o servidor validá-la.

        O cliente não decide se a ação é legal. Isso evita divergência entre os
        processos e impede que dois clientes tenham versões diferentes da
        verdade do jogo.
        """
        return self.game.submit_action(player_id, action, payload)

    def leave_game(self, player_id: str) -> dict[str, object]:
        """Remove ou marca como derrotado o jogador que saiu da partida."""
        return self.game.leave_game(player_id)


# Alias didático e compatível com os testes/código antigo.
# "Service" é o nome comum da fachada remota; "Rpc" deixa explícito o protocolo.
GameService = GameRpcService


def create_rpc_server(
    host: str = "0.0.0.0",
    port: int = DEFAULT_PORT,
    service: GameRpcService | None = None,
) -> ThreadingXMLRPCServer:
    """Cria e configura o servidor XML-RPC, mas ainda não inicia o loop.

    Separar criação de execução ajuda em testes: o teste pode criar o servidor
    em uma porta aleatória, iniciar em uma thread e encerrar quando terminar.

    Passos de rede:
    1. Abrir uma porta TCP em ``host:port``.
    2. Restringir o endpoint ao caminho ``/RPC2``.
    3. Registrar funções de introspecção, como ``system.listMethods``.
    4. Registrar o objeto remoto que contém os métodos do jogo.
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
    """Sobe o servidor e fica escutando chamadas remotas até o processo fechar.

    ``serve_forever`` é o loop de aceitação de requisições. Em termos de
    sistemas distribuídos, é aqui que o processo servidor passa a oferecer o
    serviço para outros processos na rede local.
    """
    with create_rpc_server(host, port) as server:
        print(f"Servidor de Risk ouvindo em {host}:{port}")
        server.serve_forever()
