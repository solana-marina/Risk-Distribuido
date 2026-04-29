# Risk Distribuído em Python + Pygame

Implementação de uma versão distribuída de Risk com:

- `1 servidor autoritativo` via XML-RPC
- `2 clientes pygame` em processos separados
- `mapa do mundo` baseado em asset CC BY-SA
- `cartas, missões, dados, continentes e tropas`

## Requisitos

- Python `3.13`
- `pygame 2.6.1`
- `PyTMX 3.32`

## Instalar dependências

```bash
python -m pip install -r requirements.txt
```

## Gerar o mapa TMX

O arquivo já foi gerado no projeto, mas pode ser recriado com:

```bash
python -m risk_dist.tools.generate_world_map
```

## Rodar o servidor

```bash
python -m risk_dist.server
```

Ou escolhendo `Hospedar Partida` dentro do cliente pygame.

## Rodar o cliente

```bash
python -m risk_dist.client
```

## Abrir 1 servidor + 2 clientes com um comando

```bash
python -m risk_dist.tools.abrir_partida_local
```

Esse comando:

- sobe o servidor local
- abre dois clientes pygame
- conecta os dois automaticamente
- tenta escolher cores e marcar os dois jogadores como prontos

Para um teste rápido com fechamento automático após 10 segundos:

```bash
python -m risk_dist.tools.abrir_partida_local --encerrar-apos 10
```

## Rodar os testes

```bash
python -m pytest -q
```

## Estrutura

- `risk_dist/shared`: constantes, regras e carregamento do tabuleiro
- `risk_dist/server`: motor autoritativo e camada XML-RPC
- `risk_dist/client`: interface pygame e cliente de rede
- `risk_dist/tools`: utilitário para gerar o mapa `.tmx`
- `risk_dist/assets`: tabuleiro, atribuição e metadados do mapa

## Créditos do mapa

Ver `risk_dist/assets/ATTRIBUTION.md`.
