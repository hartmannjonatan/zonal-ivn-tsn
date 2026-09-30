# Validação do catálogo completo

Carregar o ambiente OMNeT++ 6.4.0 e definir INET_ROOT para o INET 4.7.0.
Todos os comandos abaixo partem da raiz do repositório:

```bash
export INET_ROOT=/caminho/para/inet-4.7.0
bash scripts/run/build.sh
python3 scripts/run/validate_traffic.py --jobs 2
```

A compilação deve ser realizada antes de iniciar o executor.
Ele executa oito células `Validate_L0_A0` até `Validate_L3_A1`, `ValidateReseed`
(seed 42) e `ValidateSignatures`. As células normais usam seed 41, warm-up de
40 ms, dois segundos medidos e 50 ms de drenagem. A varredura isolada exercita
cada uma das dez assinaturas em F21 e F22, deterministicamente, em dez segundos;
esse modo diagnóstico não substitui o sorteio nas configurações normais.

O verificador comprova geração e encaminhamento do catálogo no suporte usado
antes dos tratamentos C0–C4. O baseline C0, com filas finitas em todos os
talkers e switches, tem validação própria em
`tests/validation/classification/README.md`.

## Execução individual e Qtenv

```bash
bash simulations/run -u Cmdenv -c Validate_L2_A1
python3 tests/validation/traffic/check_traffic.py \
  simulations/results/traffic/Validate_L2_A1-0
bash simulations/run -u Qtenv -c Traffic_L1_A0
```

Na IDE, recompilar o projeto (agora contém módulos C++), abrir
`simulations/omnetpp.ini` e escolher `Validate_Lx_Ay` para uma execução curta
ou `Traffic_Lx_Ay` para 1 s de warm-up + 30 s de geração medida + 50 ms de
drenagem. Inspecionar `trafficPlan`, as aplicações nomeadas por fluxo e as
tabelas MAC/VLAN dos switches. Executar com diretório de trabalho `simulations`,
como faz o launcher, para manter CSVs e resultados OMNeT++ juntos.

As configurações Traffic também registram `releases.csv`, permitindo usar o
mesmo verificador após a execução. Reexecutar a mesma configuração/run sobrescreve
os arquivos correspondentes: arquivar resultados que devam ser preservados.

## Evidências verificadas

- As 22 origens e os 23 receptores esperados, incluindo os dois displays de F14.
- Cada instante de liberação, quantidade por rajada, tamanho e offset/fase,
  calculados independentemente a partir dos CSVs e do fator L/A.
- Conservação de bytes de aplicação e sequências; último segmento dos eventos.
- Quadros reais em cada egresso: IPv4 ≤1500 B, VLAN, PCP, UDP, wire e IFG.
- PCP n → TCn nas filas dos switches e contabilização de descartes.
- Todos os caminhos esperados e ausência de egressos extras/flooding.
- F14 enviado uma vez pelo HPC, replicado somente em CSW.eth1/eth2 e entregue
  em Z1/Z2.ZSW.eth7; mesmas sequências e bytes nos dois displays.
- F21/F22 dentro de seus blocos, A0 sem sobreposição e A1 com início simultâneo.
- Mesmas assinaturas entre as oito células e alteração com outra seed.
- Metadados de deadline, latência máxima e misses, sem exigir que o suporte de
  tráfego satisfaça os critérios de viabilidade da campanha final.

A duração finita pode cortar ciclos de câmera em fases distintas: os totais A0
versus A1 podem diferir por uma rajada na borda da execução. O verificador usa
os instantes esperados exatos; a taxa nominal de longo prazo permanece igual.

## Arquivos de saída

Em `simulations/results/traffic/<configuração>-0/`:

| Arquivo | Conteúdo |
|---|---|
| run.csv | L/A, fator, durações e modos diagnósticos |
| events.csv | Assinatura, volume, duração e início de cada evento |
| releases.csv | Toda liberação de aplicação, com tamanho e bloco |
| Fxx-<nó>-tx/rx.csv | Contagens, bytes, sequências e deadlines |
| wire.csv | Contagens/tamanhos/sequências por fluxo e egresso real |
| queues.csv / drops.csv | Entradas em filas e descartes |
| validation.json | Relatório produzido após aprovação dos checks |

Os logs e arquivos `.sca` ficam no diretório `results/traffic` de simulations.
As falhas da auditoria encerram a simulação com erro, sem produzir um PASS.
Para conferir novamente as evidências já existentes, sem repetir simulações:

```bash
python3 scripts/run/validate_traffic.py --check-existing
```

Ver `results-summary.md` para o resumo versionado da consolidação.
