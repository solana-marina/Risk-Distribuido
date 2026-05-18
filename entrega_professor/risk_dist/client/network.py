"""Rede do cliente no Risk distribuído.

A interface gráfica não fala com XML-RPC diretamente. Ela chama métodos comuns
desta camada, como ``ready()`` e ``submit_action()``, e este módulo transforma
essas chamadas em requisições para o servidor.

Na apresentação, o ponto principal é este: cliente e servidor rodam em processos
separados e conversam pela rede usando TCP, HTTP e XML-RPC. O ``ServerProxy``
faz um papel parecido com o stub do Java RMI: ele esconde a serialização, o
envio da chamada e a leitura da resposta. O ``player_id`` é o identificador de
sessão que acompanha as chamadas para o servidor saber quem está jogando.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from xmlrpc.client import Fault, ProtocolError, ServerProxy

from risk_dist.shared.constants import DEFAULT_PORT


def endpoint_from_host_port(host: str, port: int) -> str:
    """Monta a URL que o ``ServerProxy`` usa para encontrar o serviço.

    O caminho ``/RPC2`` é a convenção da biblioteca XML-RPC do Python. Em Java
    RMI, a ideia mais próxima seria montar o endereço do registry ou do objeto
    remoto antes de fazer o ``lookup``.
    """
    return f"http://{host}:{port}/RPC2"


def normalize_endpoint(raw: str) -> tuple[str, int, str]:
    """Transforma o texto da tela de conexão em host, porta e URL XML-RPC.

    A UI deixa o jogador digitar algo simples, como ``192.168.0.10:5000``. Aqui
    completamos o ``http://`` quando ele não veio e usamos a porta padrão quando
    a pessoa informou apenas o endereço da máquina.
    """
    text = raw.strip() or f"127.0.0.1:{DEFAULT_PORT}"
    if "://" not in text:
        text = f"http://{text}"
    parsed = urlparse(text)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or DEFAULT_PORT
    endpoint = endpoint_from_host_port(host, port)
    return host, port, endpoint


def rpc_server_responding(endpoint: str) -> bool:
    """Confirma se já existe um servidor XML-RPC respondendo neste endpoint.

    O launcher local usa essa checagem antes de abrir os clientes. A chamada
    ``system.listMethods`` é pequena e funciona como um teste de vida do serviço,
    parecido com fazer um ``lookup`` simples em RMI.
    """
    try:
        proxy = ServerProxy(endpoint, allow_none=True)
        proxy.system.listMethods()
        return True
    except (Fault, ProtocolError, OSError):
        return False


@dataclass
class RpcGameClient:
    """Fachada que a UI usa para chamar o serviço remoto do jogo.

    Esta classe deixa a interface longe dos detalhes de XML-RPC. Para quem está
    usando a UI, os métodos parecem locais; por dentro, o ``ServerProxy`` monta
    chamadas remotas para métodos publicados pelo servidor.

    ``endpoint`` guarda a URL do servidor, ``player_id`` identifica a sessão do
    jogador e ``proxy`` é o stub dinâmico criado pela biblioteca ``xmlrpc``.
    """

    endpoint: str
    player_id: str | None = None
    proxy: ServerProxy | None = None

    def connect(self, name: str) -> dict[str, object]:
        """Conecta ao servidor e registra este jogador na partida.

        A primeira chamada remota é ``join_game``. Se ela der certo, o servidor
        devolve um ``player_id``; depois disso, o cliente envia esse identificador
        nas chamadas que dependem da sessão do jogador.
        """
        self.proxy = ServerProxy(self.endpoint, allow_none=True)
        try:
            result = self.proxy.join_game(name)
            if result.get("ok"):
                self.player_id = str(result["player_id"])
            return result
        except (Fault, ProtocolError, OSError) as exc:
            self.proxy = None
            if "0.0.0.0" in self.endpoint:
                return {
                    "ok": False,
                    "error": (
                        "No cliente, não use 0.0.0.0. Use 127.0.0.1 no mesmo computador "
                        "ou o IPv4 da máquina do servidor em outro computador."
                    ),
                }
            return {"ok": False, "error": f"Não foi possível conectar ao servidor: {exc}"}

    def choose_color(self, color: str) -> dict[str, object]:
        """Invoca remotamente a escolha de cor no lobby."""
        return self._call("choose_color", self.player_id, color)

    def ready(self) -> dict[str, object]:
        """Invoca remotamente a confirmação de pronto do jogador."""
        return self._call("ready", self.player_id)

    def poll_snapshot(self, last_version: int | None) -> dict[str, object]:
        """Pergunta ao servidor se existe uma versão mais nova do jogo.

        A UI chama este método de tempos em tempos. Isso é polling: o cliente
        pergunta se algo mudou, e o servidor só envia o snapshot completo quando
        a versão é mais recente que ``last_version``.
        """
        return self._call("get_snapshot", self.player_id, last_version)

    def submit_action(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        """Envia uma jogada para o servidor validar e aplicar.

        A UI só descreve a intenção do jogador. Quem decide se um ataque,
        reforço ou troca de cartas é válido é o servidor, que mantém o estado
        oficial da partida.
        """
        return self._call("submit_action", self.player_id, action, payload)

    def disconnect(self) -> None:
        """Tenta avisar ao servidor que este cliente saiu.

        A desconexão é feita sem travar a interface: se a rede caiu ou a janela
        já está fechando, o cliente simplesmente segue encerrando.
        """
        if not self.proxy or not self.player_id:
            return
        try:
            self.proxy.leave_game(self.player_id)
        except (Fault, ProtocolError, OSError):
            pass

    def _call(self, method: str, *args: object) -> dict[str, object]:
        """Executa uma chamada remota e devolve erro em formato que a UI entende.

        Falhas de TCP, HTTP ou XML-RPC viram ``{"ok": False, "error": "..."}``.
        Assim a interface não precisa conhecer exceções de rede para mostrar uma
        mensagem ao jogador.
        """
        if not self.proxy:
            return {"ok": False, "error": "Cliente não conectado ao servidor."}
        try:
            rpc_method = getattr(self.proxy, method)
            return rpc_method(*args)
        except (Fault, ProtocolError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
