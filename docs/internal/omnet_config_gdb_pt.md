# Verificação interna da configuração OMNeT++/INET (uso interno, não vai para o artigo)

Data: 2026-11-17. Cenário: `ZonalIVNT1SPowertrain` (dois barramentos 10BASE-T1S, Z1 = motor, Z3 = transmissão), OMNeT++ 6.4.0 + INET (servidor VECTOR).
Objetivo: conferir, com o próprio simulador, que a rede está configurada como pretendemos, e seguir um pedido/resposta crítico Z1 → Z3 → Z1 (PT02, ECM → APP → ECM) salto a salto.

## 1. Como a rede está configurada (parâmetros efetivos)

Os parâmetros foram extraídos pelo próprio OMNeT++ (`--**.param-recording=true`, config `TA_NOMINAL_EVC_G35_R150_30s`). Não vêm de leitura do `.ini`.

| elemento | configuração efetiva |
|---|---|
| CSW (switch central) | `inet.node.tsn.TsnSwitch`, portas 1 Gb/s: eth0 = HPC, eth1 = Z1, eth2 = Z2, eth3 = Z3 |
| filas de saída (CSW e portas de backbone dos ZSW) | `Ieee8021qTimeAwareShaper` com 8 classes; `PcpTrafficClassClassifier` com mapeamento identidade (PCP i → fila i); `PriorityScheduler` com `reverseOrder = true` (fila 7 tem prioridade); `DropTailQueue` de 1 MiB por classe |
| gates (CSW e backbone) | todos abertos (`initiallyOpen = true`, `durations = []`): **não há TAS no CSW**, apenas prioridade estrita |
| portas T1S dos zonais (Z1.ZSW eth5, Z3.ZSW eth6) | 10 Mb/s, `EthernetPlcaInterface`, coordenador PLCA (`local_nodeID = 0`, `plca_node_count = 6`), `PrioPlca` em modo `anchored` (TA-PLCA), `max_bc = 1`, `to_timer = 32 bit`; **TAS só aqui**, no gate da classe 3 (janela) |
| switches | `hasCutthroughSwitching = false` (store-and-forward), `hasGptp = true`, sem filtragem de ingresso, sem preempção, sem redundância |
| relógios | gPTP (`inet.linklayer.ieee8021as.Gptp`, `BRIDGE_NODE` no CSW), `SettableClock` + oscilador com deriva constante |
| tráfego powertrain | VLAN própria, PCP 7 em todos os nós (`streamCoder`), quadros de 64 B na fila de saída (8 B de carga útil) |

Conclusão: a configuração bate com a intenção. São 8 filas por porta com prioridade estrita, o TAS fica só nas portas T1S dos zonais e não há shaping no CSW.

## 2. Método (gdb)

- Build de debug de INET, `prioplca` e `src` com `-ggdb`. O padrão do OMNeT++ é `-glldb`, que o gdb 17 não lê com clang 21 e faz o gdb abortar. O script carrega símbolos só das bibliotecas necessárias, porque a `liboppqtenv_dbg` também tem esse problema.
- Script: `scripts/gdb/trace_pt02.py`. Os breakpoints não param a simulação: imprimem e seguem.
  - `RelayInterfaceSelector::pushPacket`: chegada do quadro ao relay do switch, que decide a porta de saída.
  - `PacketQueue::pushPacket` / `pullPacket`: entrada na fila de saída e saída para o MAC. O índice da fila é a classe de tráfego, ou seja, o PCP.
  - `EthernetPlca::startFrameTransmission` / `handleReceptionEnd`: entrega ao PLCA e recepção completa no barramento T1S.
  - Em cada evento: tempo de simulação, módulo, tamanho, ocupação das 8 filas da porta e backtrace.
- Para não pegar o transitório de partida, o rastreio só é armado depois do warm-up de 1 s. O pacote seguido é o PT02-100, liberado em ≈ 1,010 s.
- Rodamos dois casos: TA-PLCA v2 (`TA_NOMINAL_EVC_G35_R150_30s`) e o baseline com agenda gPTP + TAS (`TA_NOMINAL_GPTP_30s`).

## 3. Resultado: PT02 com TA-PLCA v2 (tempos relativos à liberação t0 = 1 010 001,28 µs)

| t (µs) | onde | o que acontece |
|---|---|---|
| 0,00 | ECM | pedido (64 B) entregue ao PLCA; espera a âncora do ciclo planejado |
| 81,81 | Z1.ZSW eth5 | recebido do barramento Z1 (espera pela âncora + 64 B a 10 Mb/s) |
| 81,81 | Z1.ZSW relay → eth0 fila[7] | fila vazia, sai na hora (todas as 8 filas vazias) |
| 82,49 | CSW relay → eth3 fila[7] | 0,676 µs por salto = 72 B a 1 Gb/s + 0,1 µs de propagação; filas vazias |
| 83,17 | Z3.ZSW relay → eth6 fila[7] | **fila[3] (janela) com 6 quadros, o PT02 passa à frente** (prioridade estrita) |
| 181,40 | APP | pedido recebido (entregue na âncora planejada do Z3) |
| 184,65 | APP | resposta pronta (processamento ≈ 3 µs, `DelayedUdpEchoApp`) |
| 350,60 | Z3.ZSW eth6 | resposta recebida no ciclo de resposta planejado (R = 150 µs após a entrega) |
| 350,60 → 351,95 | Z3.ZSW → CSW eth1 → Z1.ZSW | filas[7] vazias nos três switches, 0,676 µs por salto |
| 351,95 | Z1.ZSW eth5 fila[7] | fila[3] com 7 quadros da janela, a resposta passa à frente |
| **440,41** | ECM | resposta recebida: **RTT = 440,41 µs**, igual ao valor da campanha (440,41 µs, variação < 0,1 µs) |

## 4. Mesmo pedido com a agenda gPTP + TAS (baseline)

O caminho é o mesmo, com as mesmas filas e o mesmo PCP, e o backbone também está vazio. A diferença está só nos barramentos T1S:
- No Z3.ZSW eth6, o quadro esperou 9,9 µs na fila (o ciclo PLCA estava no meio) e foi entregue no TO do coordenador seguinte.
- No Z1.ZSW eth5, a resposta chegou com o ciclo em `curID = 2`. O coordenador já tinha passado do seu TO 0, então a resposta esperou **um ciclo PLCA inteiro** (de 317,8 a 400,6 µs) para sair.
- RTT dessa amostra: 432,72 µs. Na campanha esse valor varia centenas de µs (seção 6.4 de `taplca.md`), justamente porque a espera depende da fase do ciclo PLCA quando o quadro chega.

É exatamente o efeito que o TA-PLCA remove: com as âncoras, o ciclo começa quando o quadro já está no coordenador.

## 5. Pontos a observar (para discutir com o Guto)

1. **Switches sem atraso de processamento.** No INET, o relay encaminha no mesmo instante da recepção completa. Só há store-and-forward (0,576 µs de transmissão + 0,1 µs de propagação por salto). Um switch real adiciona de 1 a 5 µs por salto. No nosso orçamento isso é pequeno (4 saltos por sentido), mas, se quisermos, dá para modelar com `bridging.processingDelayLayer`, que já existe no `TsnSwitch`.
2. **O backbone de 1 Gb/s nunca teve fila para o PCP 7** nos pacotes seguidos. Toda a variação está nos segmentos T1S, como esperado.
3. **As filas da janela (classe 3) acumulam de 6 a 8 quadros** nas portas T1S: é o custo do gate fechado. O PCP 7 sempre passou à frente, confirmando a prioridade estrita.
4. O tamanho no relay aparece como 42 B, sem cabeçalho MAC nem FCS, e na fila de saída como 64 B, já com o padding mínimo. Isso é coerente.
5. O APP aparece com duas entregas ao PLCA (`curID = 0` e depois `curID = 3`). A primeira tentativa cai fora do TO do nó, e o quadro só sai no TO 3. É o comportamento normal do PLCA no INET.

## 6. Como repetir

```
# build de debug (uma vez): INET, prioplca e src com
make MODE=debug CFLAGS_DEBUG="-O0 -Wall -ggdb -fstandalone-debug"
cd simulations
PKT=PT02-100 gdb -batch -x ../scripts/gdb/trace_pt02.py --args ../src/zonal-ivn-tsn_dbg \
  -n ".:../src:../tests:$INET_ROOT/src:../prioplca" -l ../prioplca/prioplca \
  -f zonal_t1s_taplca.ini -u Cmdenv -c TA_NOMINAL_EVC_G35_R150_30s -r 0 --sim-time-limit=1.0112s
```
Leva cerca de 1 h por caso, porque a simulação de debug roda devagar até o rastreio ser armado.
