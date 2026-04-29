"""Camada cliente de rede do Risk distribuído.

Este arquivo concentra tudo que o cliente pygame precisa saber sobre rede.
O restante da interface chama métodos Python comuns, como ``ready()`` ou
``submit_action()``, e esta camada traduz essas chamadas para XML-RPC.

Relação com sistemas distribuídos:
- O cliente e o servidor rodam em processos diferentes.
- A comunicação passa pela rede usando TCP + HTTP + XML-RPC.
- XML-RPC implementa a ideia de RPC, ou seja, chamada de procedimento remoto.
- Para o cliente, ``self.proxy.join_game(nome)`` parece uma chamada local.
- Na prática, o ``ServerProxy`` serializa os argumentos, envia pela rede,
  espera a resposta do servidor e desserializa o resultado.

Paralelo com Java RMI:
- ``ServerProxy`` faz o papel aproximado do stub retornado por
  ``Naming.lookup(...)`` ou ``LocateRegistry.getRegistry(...).lookup(...)``.
- Cada método desta classe parece uma chamada em uma interface remota Java.
- ``player_id`` funciona como um identificador de sessão, parecido com um
  token que o cliente envia em cada chamada para o servidor saber quem chamou.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
from xmlrpc.client import Fault, ProtocolError, ServerProxy

from risk_dist.shared.constants import DEFAULT_PORT


def endpoint_from_host_port(host: str, port: int) -> str:
    """Monta a URL padronizada do endpoint XML-RPC.

    Em XML-RPC, o cliente precisa conhecer a URL do serviço remoto. Neste
    projeto usamos o caminho padrão ``/RPC2`` porque é o caminho esperado pela
    biblioteca ``xmlrpc`` do Python.

    Paralelo em Java RMI:
    - Aqui montamos ``http://host:porta/RPC2``.
    - Em Java seria comum usar algo como ``//host:porta/NomeDoServico`` ou
      obter o registry com ``LocateRegistry.getRegistry(host, porta)``.
    """
    return f"http://{host}:{port}/RPC2"


def normalize_endpoint(raw: str) -> tuple[str, int, str]:
    """Normaliza o texto digitado pelo usuário para host, porta e URL RPC.

    A interface aceita entradas simples, como ``192.168.0.10:5000``. Esta
    função completa o protocolo ``http://`` quando ele não aparece e aplica a
    porta padrão do jogo quando a pessoa digitou apenas o IP.

    Conceito distribuído:
    - Antes de invocar um método remoto, o cliente precisa localizar o serviço.
    - Esta função resolve o "endereço lógico" digitado na UI para um endpoint
      concreto que pode ser usado pelo stub XML-RPC.
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
    """Verifica se um servidor XML-RPC responde no endpoint informado.

    O launcher local usa isto para esperar o servidor ficar pronto antes de
    abrir os dois clientes. A chamada ``system.listMethods`` é fornecida pela
    introspecção XML-RPC registrada no servidor.

    Paralelo em Java RMI:
    - Seria parecido com fazer um ``lookup`` no registry e talvez chamar um
      método simples de teste no objeto remoto.
    """
    try:
        proxy = ServerProxy(endpoint, allow_none=True)
        proxy.system.listMethods()
        return True
    except (Fault, ProtocolError, OSError):
        return False


@dataclass
class RpcGameClient:
    """Stub do cliente para o serviço remoto do jogo.

    A UI não acessa ``ServerProxy`` diretamente. Ela usa esta classe como uma
    pequena fachada, o que deixa a comunicação distribuída isolada em um ponto
    fácil de explicar.

    Campos importantes:
    - ``endpoint`` é a URL do servidor remoto.
    - ``player_id`` é recebido no login e enviado nas chamadas seguintes.
    - ``proxy`` é o stub dinâmico criado pela biblioteca ``xmlrpc.client``.

    Paralelo com Java:
    - Em RMI, o stub costuma implementar uma interface remota, por exemplo
      ``RiskRemote``.
    - Em Python XML-RPC, o ``ServerProxy`` é dinâmico: se chamarmos
      ``proxy.ready(...)``, ele tenta invocar o método remoto chamado
      ``ready`` no servidor.
    """

    endpoint: str
    player_id: str | None = None
    proxy: ServerProxy | None = None

    def connect(self, name: str) -> dict[str, object]:
        """Cria o stub XML-RPC e registra este jogador no servidor.

        A primeira chamada remota é ``join_game``. O servidor responde com um
        ``player_id``; a partir daí o cliente envia esse identificador em todas
        as chamadas que dependem do jogador.

        Conceito distribuído:
        - O servidor mantém o estado autoritativo da sessão.
        - O cliente guarda apenas uma referência lógica para essa sessão.
        """
        self.proxy = ServerProxy(self.endpoint, allow_none=True)
        result = self.proxy.join_game(name)
        if result.get("ok"):
            self.player_id = str(result["player_id"])
        return result

    def choose_color(self, color: str) -> dict[str, object]:
        """Invoca remotamente a escolha de cor no lobby."""
        return self._call("choose_color", self.player_id, color)

    def ready(self) -> dict[str, object]:
        """Invoca remotamente a confirmação de pronto do jogador."""
        return self._call("ready", self.player_id)

    def poll_snapshot(self, last_version: int | None) -> dict[str, object]:
        """Busca o estado do jogo quando houver uma versão nova.

        A UI chama este método periodicamente. Isso é um modelo simples de
        polling: em vez de o servidor empurrar eventos para o cliente, o
        cliente pergunta se existe uma versão mais recente.

        Conceito distribuído:
        - ``last_version`` reduz tráfego de rede, pois o servidor só manda o
          snapshot completo quando o estado mudou.
        - O snapshot enviado ao cliente é uma cópia serializável do estado, não
          o objeto real do servidor.
        """
        return self._call("get_snapshot", self.player_id, last_version)

    def submit_action(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        """Envia uma ação genérica do jogador para o servidor autoritativo.

        A UI não decide se um ataque, reforço ou troca de cartas é válido. Ela
        envia a intenção, e o servidor valida com as regras oficiais do jogo.

        Paralelo com Java:
        - Poderíamos ter vários métodos remotos, como ``attack(...)`` e
          ``fortify(...)``.
        - Aqui usamos um envelope ``submit_action(acao, dados)`` para manter a
          interface remota menor e mais fácil de evoluir.
        """
        return self._call("submit_action", self.player_id, action, payload)

    def disconnect(self) -> None:
        """Informa ao servidor que este cliente saiu.

        A desconexão é "best effort": se a janela já está fechando ou a rede
        caiu, não vale travar a interface tentando avisar o servidor.
        """
        if not self.proxy or not self.player_id:
            return
        try:
            self.proxy.leave_game(self.player_id)
        except Exception:
            pass

    def _call(self, method: str, *args: object) -> dict[str, object]:
        """Executa uma chamada remota e converte falhas de rede em dicionário.

        Sem esta camada, uma falha TCP, HTTP ou XML-RPC poderia lançar exceção
        direto na interface pygame. Aqui padronizamos o erro como
        ``{"ok": False, "error": "..."}``, que a UI já sabe mostrar.

        Tipos de falha:
        - ``OSError``: servidor fora do ar, conexão recusada ou rede indisponível.
        - ``ProtocolError``: erro HTTP, como resposta inválida do servidor.
        - ``Fault``: exceção XML-RPC retornada pelo servidor remoto.
        """
        if not self.proxy:
            return {"ok": False, "error": "Cliente não conectado ao servidor."}
        try:
            rpc_method = getattr(self.proxy, method)
            return rpc_method(*args)
        except (Fault, ProtocolError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
