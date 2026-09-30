# Topologia P1 — implementada

A rede `zonal_ivn_tsn.simulations.zonal.networks.ZonalIVN` implementa as seções
2.2–2.4 do P1: 25 endpoints TsnDevice (HPC, três CPUs e 21 dispositivos locais),
quatro TsnSwitch e 28 enlaces full-duplex. A configuração mantém switches
store-and-forward, sem STP, erros físicos, redundância ou encaminhamento pelas
CPUs. O configurador calcula os caminhos únicos da árvore na inicialização;
não há protocolo de roteamento dinâmico nem aprendizado MAC durante a execução.

## Inspeção no OMNeT++ / Qtenv

1. Importar/compilar INET 4.7.0 e este projeto no workspace OMNeT++ 6.4.0.
   Conferir as raízes NED `src`, `simulations`, `tests` e a referência ao INET.
2. Abrir `simulations/omnetpp.ini` e executar com **Qtenv**, configuração
   **TopologyValidation**. Inicializar e ajustar o zoom para enquadrar a rede.
3. Conferir HPC→CSW e os três ramos LB sobre o fundo do veículo (1280×720).
   A frente aponta para a direita; Z1 fica acima à direita (dianteira esquerda
   do veículo), Z2 abaixo à direita e Z3 na traseira, à esquerda.
   Os nomes são os do P1; Z1/Z2/Z3 representam os controladores compostos.
4. Abrir Z1, Z2 e Z3 com duplo clique: cada um contém **ZSW**, **ZCPU** e **LP**.
   `Z1.ZSW` corresponde a Z1_SW no P1 e `Z1.ZCPU` a Z1_CPU; idem Z2/Z3.
   As portas externas chegam diretamente ao switch, sem canal ou atraso extra.
5. Inspecionar canais e `eth[n].bitrate` conforme as tabelas abaixo. Todos os
   canais físicos têm `delay=100ns`, `length=20m`, `ber=per=0`. Cada `<-->`
   contém dois canais direcionais, um para cada sentido full-duplex.
6. Inspecionar `CSW.macTable` e `Z*.ZSW.macTable`: as entradas unicast já estão
   instaladas. `HPC` e `Z*.ZCPU` têm `forwarding=false`.
7. Executar **TopologyConnectivity** para animar sondas ICMP. Em modo normal,
   reduzir a velocidade de animação para acompanhar os caminhos. Esperado:
   HPC 48/48 respostas e LiDAR1, Z1.ZCPU, Z2.ZCPU com 2/2 cada.

`TopologyValidation` não gera aplicações: terminar sem pacotes é esperado.
SYNC não é outro nó; será o relógio do HPC em C4. As sondas são diagnósticas,
sem VLAN/PCP ou taxas/deadlines do catálogo. Não são resultados C0.

## Distribuição visual sobre o veículo

O fundo é o original `background/car` do showcase INET InVehicleNetworkShowcase.
A câmera usa `misc/camera`; scanner e antena direcional distinguem LiDAR e radar,
com rótulos explícitos. O fundo não é coberto por painéis de zona opacos.

- CAM1/CAM2: cantos dianteiros esquerdo/direito; CAM3/CAM4: cantos traseiros.
- LiDAR1: região frontal, ligado a Z1; RADAR1: região frontal direita, ligado a
  Z2; RADAR2: extremidade traseira, ligado a Z3.
- BRAKE1/BRAKE2: rodas dianteiras; BRAKE3: região da roda traseira esquerda.
  O benchmark tem um único BRAKE3; não se adiciona outro nó para a segunda roda.
- WINDOW1/WINDOW2: laterais dianteiras; WINDOW3: lateral traseira.
  AUDIO e DISPLAY ficam na cabine; HPC/CSW no centro e BE perto do controlador.

O P1 define zonas e conexões, mas não coordenadas de montagem: as posições são
ilustrativas, usando a orientação do showcase como referência. A distância no
desenho não altera o comprimento/atraso uniforme dos canais. A atribuição dos
21 dispositivos às três zonas permanece a mesma.

O caminho local `image-path = ../images` disponibiliza carro e câmera tanto na
IDE quanto na execução por linha de comando; não exige caminho absoluto do INET.
As cores dos enlaces e a legenda indicam classe/velocidade. Os detalhes dos
acessos estão nos tooltips e nos parâmetros dos canais, evitando texto sobreposto
à imagem do carro. Os nomes LC/LB continuam visíveis no backbone.

## Enlaces e portas estáveis

| Grupo | Quantidade | Capacidade | Conexão |
|---|---:|---|---|
| LC | 1 | 1 Gbit/s | HPC eth0 ↔ CSW eth0 |
| LB1–LB3 | 3 | 1 Gbit/s | CSW eth1/2/3 ↔ Z1/2/3.ZSW eth0 |
| LP | 3 | 1 Gbit/s | Z*.ZSW eth1 ↔ Z*.ZCPU eth0 |
| LA-H | 5 | 1 Gbit/s | LiDAR1 e CAM1–CAM4 ↔ switch local |
| LA-L | 16 | 100 Mbit/s | Demais dispositivos ↔ switch local |

Cada endpoint tem apenas eth0. No controlador, `access[i]` corresponde a
`ZSW.eth[i+2]`; `uplink` corresponde a `ZSW.eth[0]`.

| Porta ZSW | Z1 | Z2 | Z3 |
|---|---|---|---|
| eth0 | CSW | CSW | CSW |
| eth1 | Z1_CPU | Z2_CPU | Z3_CPU |
| eth2 | LiDAR1 (1G) | RADAR1 (100M) | RADAR2 (100M) |
| eth3 | CAM1 (1G) | CAM2 (1G) | CAM3 (1G) |
| eth4 | BRAKE1 (100M) | BRAKE2 (100M) | CAM4 (1G) |
| eth5 | WINDOW1 (100M) | WINDOW2 (100M) | BRAKE3 (100M) |
| eth6 | AUDIO1 (100M) | AUDIO2 (100M) | WINDOW3 (100M) |
| eth7 | DISPLAY1 (100M) | DISPLAY2 (100M) | AUDIO3 (100M) |
| eth8 | BE1 (100M) | BE2 (100M) | BE3 (100M) |

Os sete egressos reservados para TAS em C4 são HPC.eth0, CSW.eth1/2/3,
Z1.ZSW.eth4, Z2.ZSW.eth4 e Z3.ZSW.eth5. TAS permanece desativado nesta etapa.

## Reprodução em Cmdenv

Com o ambiente OMNeT++ carregado, executar na raiz do repositório. Ajustar
`INET_ROOT` para a instalação local; não é necessário compilar novos módulos C++.

```bash
export INET_ROOT=/caminho/para/inet-4.7.0
opp_run -u Cmdenv -n "simulations:src:tests:$INET_ROOT/src" \
  -l "$INET_ROOT/src/INET" -f simulations/omnetpp.ini -c TopologyValidation
opp_run -u Cmdenv -n "simulations:src:tests:$INET_ROOT/src" \
  -l "$INET_ROOT/src/INET" -f simulations/omnetpp.ini -c TopologyConnectivity
python3 tests/validation/topology/check_topology.py \
  'simulations/results/topology/TopologyValidation-#0.sca'
python3 tests/validation/topology/check_topology.py \
  'simulations/results/topology/TopologyConnectivity-#0.sca'
```

O verificador lê parâmetros e tabelas produzidos pela simulação: inventário de
nós/enlaces, 56 bitrates nas interfaces, capacidades e atrasos nas duas direções,
número de portas, flags de mecanismos e caminho unicast para cada endpoint em
cada switch. Na configuração com sondas também exige as 54 respostas esperadas.
As saídas ficam em `simulations/results/topology/` e não são versionadas.

Validação realizada em 2026-09-28: ambas as configurações terminaram normalmente
em 1 s; todos os critérios do verificador passaram, com 54/54 respostas ICMP.
A inspeção visual interativa em Qtenv fica disponível pelos passos acima; os
checks automatizados foram realizados em Cmdenv.

## Preparação para o catálogo

Todos os destinos e os caminhos P1–P4 estão disponíveis. Os nomes e as portas
acima são o contrato para aplicações, VLAN/PCP, instrumentação e shaping.
A árvore oferece a ramificação de F14 no CSW para DISPLAY1/DISPLAY2.
A inscrição multicast, a VLAN e a aplicação estão implementadas na etapa de tráfego.
As configurações Traffic/Validate implementam F01–F22 e filas por classe nos
switches. TopologyValidation permanece sem tráfego de aplicação. CBS, TAS e
gPTP ainda são etapas posteriores.
