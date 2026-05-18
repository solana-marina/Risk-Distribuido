# Risk Distribuído

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13+-blue" />
  <img src="https://img.shields.io/badge/Pygame-2.6.1-green" />
  <img src="https://img.shields.io/badge/XML--RPC-Cliente--Servidor-orange" />
  <img src="https://img.shields.io/badge/Sistemas%20Distribu%C3%ADdos-RPC%20%7C%20RMI-0055A4" />
</p>

Projeto desenvolvido por **Solana Marina Bonfim Lemos** para a disciplina de
**Sistemas Distribuídos**. O trabalho implementa uma versão jogável e distribuída
do jogo **Risk**, com um servidor central em Python e dois clientes gráficos em
Pygame conectados por XML-RPC.

O foco didático do projeto é demonstrar, na prática, uma aplicação
cliente-servidor com chamada de procedimento remoto, estado compartilhado
centralizado, concorrência no servidor e sincronização de clientes por snapshots.

## O Que Foi Implementado

- Servidor autoritativo que mantém o estado oficial da partida.
- Dois clientes gráficos independentes, executados em processos separados.
- Comunicação remota via XML-RPC sobre HTTP/TCP.
- Lobby com conexão, escolha de cor e confirmação de pronto.
- Distribuição de territórios, missões secretas, tropas iniciais e cartas.
- Fases de preparação, reforço, ataque, defesa, conquista, manobra e fim de jogo.
- Rolagem de dados no servidor, com resultado enviado aos clientes.
- Cartas de território, curingas, trocas de cartas e reforços por continente.
- Snapshots personalizados: missão secreta e cartas aparecem apenas para o dono.
- Log de eventos e interface com mapa, territórios, cartas, regras e dados.

## Estrutura Do Projeto

```text
risk_dist/
  client/
    __main__.py       Entrada do cliente.
    network.py        Stub XML-RPC usado pela interface.
    ui.py             Interface gráfica em Pygame.
  server/
    __main__.py       Entrada do servidor.
    game.py           Regras e estado autoritativo da partida.
    network.py        Serviço remoto XML-RPC publicado aos clientes.
  shared/
    board.py          Carregamento e geometria do mapa.
    constants.py      Constantes do jogo, cores, missões e caminhos.
    rules.py          Funções de regra compartilhadas.
  assets/
    board.png         Imagem do tabuleiro.
    world_map.tmx     Mapa de territórios.
requirements.txt
README.md
```

Na pasta `entrega_professor/`, os arquivos de mídia ficam separados em
`midia/`, mantendo o código-fonte limpo.

## Requisitos

- Python 3.13 ou superior.
- Dependências instaladas com:

```bash
python -m pip install -r requirements.txt
```

Dependências principais:

- `pygame==2.6.1`
- `PyTMX==3.32`

O servidor usa apenas bibliotecas padrão do Python para XML-RPC, HTTP, TCP e
threads.

## Como Executar

Abra um terminal na pasta do projeto e inicie o servidor:

```bash
python -m risk_dist.server --host 0.0.0.0 --port 5000
```

No mesmo computador, abra o primeiro cliente:

```bash
python -m risk_dist.client --nome JogadorA --servidor 127.0.0.1:5000
```

Abra um segundo terminal para o segundo cliente:

```bash
python -m risk_dist.client --nome JogadorB --servidor 127.0.0.1:5000
```

Para jogar em computadores diferentes na mesma rede, mantenha o servidor com
`--host 0.0.0.0` e conecte os clientes ao IPv4 mostrado no terminal do servidor,
por exemplo:

```bash
python -m risk_dist.client --nome JogadorB --servidor 192.168.0.10:5000
```

Observação: `0.0.0.0` é endereço de escuta do servidor. O cliente deve usar
`127.0.0.1` no mesmo computador ou o IPv4 real da máquina do servidor.

## Arquitetura

### Servidor

O servidor é o dono da verdade da partida. Ele recebe ações dos clientes, valida
as regras e só então altera o estado do jogo.

Componentes principais:

- `GameRpcService`, em `risk_dist/server/network.py`, é o objeto remoto publicado
  via XML-RPC.
- `ThreadingXMLRPCServer` atende requisições em threads separadas, permitindo que
  dois clientes chamem o servidor ao mesmo tempo.
- `RiskGame`, em `risk_dist/server/game.py`, armazena jogadores, territórios,
  missões, cartas, fase atual, dados, batalha pendente e log.
- O estado compartilhado é protegido por `threading.RLock`, evitando conflitos
  quando chamadas remotas chegam em paralelo.

### Cliente

O cliente é responsável pela interface visual. Ele não decide regras da partida.
Quando o jogador clica em atacar, reforçar ou encerrar turno, a UI envia a
intenção ao servidor.

Componentes principais:

- `RpcGameClient`, em `risk_dist/client/network.py`, funciona como stub de rede.
- `ServerProxy`, da biblioteca `xmlrpc.client`, transforma chamadas Python em
  requisições XML-RPC.
- A UI faz polling com `get_snapshot(player_id, last_version)` para receber
  mudanças de estado sem baixar o jogo inteiro a cada quadro.

## Protocolo Da Aplicação

O projeto usa XML-RPC sobre HTTP/TCP. O endpoint padrão é:

```text
http://host:porta/RPC2
```

Em Python, uma chamada remota se parece com uma chamada local:

```python
resultado = proxy.submit_action(
    player_id,
    "attack",
    {"from": "brazil", "to": "peru", "dice": 3},
)
```

Esse comportamento é o paralelo principal com Java RMI: o cliente usa um stub
para chamar métodos de um objeto remoto sem manipular sockets diretamente.

### Chamadas Cliente Para Servidor

| Chamada | Função |
| --- | --- |
| `join_game(name)` | Registra um jogador e devolve seu `player_id`. |
| `choose_color(player_id, color)` | Define a cor do jogador no lobby. |
| `ready(player_id)` | Marca o jogador como pronto. |
| `get_snapshot(player_id, last_version)` | Busca o estado visível ao jogador. |
| `submit_action(player_id, action, payload)` | Envia uma ação de jogo para validação. |
| `leave_game(player_id)` | Avisa que o cliente saiu da partida. |

Ações aceitas em `submit_action`:

```text
place_setup_army
trade_cards
place_reinforcements
attack
defend
capture_move
fortify
end_attack_phase
end_turn
```

### Respostas Importantes

Sucesso:

```json
{"ok": true}
```

Erro:

```json
{"ok": false, "error": "Não é a sua vez de atacar."}
```

Snapshot atualizado:

```json
{
  "updated": true,
  "version": 30,
  "snapshot": {
    "phase": "attack",
    "current_player_id": "uuid-do-jogador-atual",
    "winner_id": null,
    "territories": [],
    "players": [],
    "your_hand": [],
    "your_trade_sets": [],
    "must_trade": false,
    "pending_prompt": null,
    "last_battle": null,
    "log": []
  }
}
```

Snapshot sem mudança:

```json
{
  "updated": false,
  "version": 30,
  "snapshot": null
}
```

## Por Que TCP

O XML-RPC trafega sobre HTTP, que usa TCP. Para este projeto, TCP é mais adequado
que UDP porque Risk é um jogo por turnos:

- As ações precisam chegar com confiabilidade.
- A ordem das ações importa para manter a partida consistente.
- Pequena latência não prejudica a jogabilidade.
- O estado do cliente deve permanecer sincronizado com o estado autoritativo do
  servidor.

## Pontos Para Apresentar Ao Professor

- A separação entre `client/`, `server/` e `shared/` mostra a divisão de
  responsabilidades.
- `GameRpcService` é o objeto remoto publicado pelo servidor.
- `RpcGameClient` é o stub usado pelo cliente, equivalente conceitual ao stub do
  Java RMI.
- `submit_action` mantém a interface remota pequena e flexível.
- `get_snapshot` reduz tráfego porque o servidor só envia estado completo quando
  a versão mudou.
- O servidor valida as regras e impede que clientes diferentes criem versões
  divergentes da partida.
- As threads do servidor permitem chamadas concorrentes, enquanto `RiskGame`
  protege o estado com lock.

## Mídias Da Entrega

A pasta de entrega inclui arquivos de demonstração para facilitar a avaliação:

```text
midia/
  demo_partida.gif
  partida_completa.mp4
  partida_completa_atualizada.mp4
```

O GIF mostra rapidamente a interface e o fluxo da partida. Os vídeos registram
uma execução mais completa do jogo.

## Validação

Com o ambiente instalado, as verificações locais usadas antes da entrega foram:

```bash
python -m pylint risk_dist.client.network risk_dist.server.network
python -m pytest
```

Resultado obtido na parte de rede:

```text
Your code has been rated at 10.00/10
```

Resultado dos testes locais:

```text
9 passed
```

## Conteúdo Da Pasta De Entrega

A pasta `entrega_professor/` foi montada para conter apenas o necessário:

```text
entrega_professor/
  README.md
  requirements.txt
  risk_dist/
    client/
    server/
    shared/
    assets/
  midia/
    demo_partida.gif
    partida_completa.mp4
    partida_completa_atualizada.mp4
```

Arquivos de cache, ambiente local, `.git`, `.pytest_cache`, `__pycache__`, testes
temporários e ferramentas auxiliares de gravação não fazem parte da entrega
principal.
