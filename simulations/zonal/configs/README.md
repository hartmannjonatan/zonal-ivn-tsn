# Configurações executáveis e contratos

A entrada é `simulations/omnetpp.ini`.

| Arquivo | Responsabilidade |
|---|---|
| base.ini / topology.ini / recording.ini | Validação isolada da topologia |
| catalog-bindings.ini | Gerado: aplicações, streams, VLAN/PCP e tabelas MAC |
| loads.ini | Seleção L0–L3 |
| aggregation.ini | Seleção A0/A1 |
| classification.ini | Suporte de classificação/buffers usado pela validação do catálogo |
| traffic.ini | Carga, RNG, resultados e validação do catálogo |
| mechanisms/C0_strict_priority.ini | Tratamento C0 executável e validação de aceitação L0–L3/A0–A1 |
| mechanisms/C1_source_preshaping.ini | C1 executável; espaçamento de origem F02–F05 |
| mechanisms/C2_nominal_cbs.ini | C2 executável; matriz seed 41 e instrumentação de crédito CBS |
| mechanisms/C2_nominal_rates.ini | Gerado: reservas nominais por egress/classe/carga |
| mechanisms/C3–C4 / synchronization.ini | Contratos das próximas configurações |
| synchronization.ini | Contrato gPTP para a etapa C4 |

`TopologyValidation` é a rede sem aplicações; `TopologyConnectivity` usa ICMP;
`SmokeTest` continua como alias. `Traffic_Lx_Ay` valida o catálogo sob seu suporte,
enquanto `C0_Lx_Ay` aplica o baseline P1 de prioridade estrita. C0 ativa filas
classificadas também nos talkers, com gates sempre abertos, SP TC7→TC0 e filas
drop-tail finitas por classe. As validações `Validate_C0_Lx_Ay` usam a mesma
configuração de filas por 1 s de warm-up, 30 s de medição e 50 ms de drenagem,
coletando latência e ocupação por classe para a análise de estabilidade. As
configurações C0 de campanha usam 1 s de warm-up,
30 s de medição e 50 ms de drenagem. Na configuração anterior de 32 KiB,
F02–F05 perdiam 30% nos egressos das câmeras. A matriz corrigida de 64 KiB foi
executada nas oito células de seed 41: zero drops, zero overflow CAM e nenhuma
fila com crescimento sustentado; 1/8 células passou o gate de viabilidade
depois de classificar F01/F06/F07 como `high-hard`. Resultados em
`simulations/results/C0/p1-validation-64KiB/`; o resumo da matriz antiga está
em `tests/validation/classification/c0-p1-results.md`. O gate de
catálogo canônico agora classifica F01/F06/F07 como `high-hard`, com XML e
bindings regenerados.
`Validate_Lx_Ay` usa 40 ms de warm-up e
2 s medidos; `ValidateReseed` verifica seed diferente. `ValidateSignatures`
percorre deterministicamente todas as assinaturas, somente com F21/F22.

`C0_strict_priority.ini` determina buffers de 128 KiB por TC nos egressos G1–G4,
64 KiB por TC nos talkers CAM1–CAM4 e 32 KiB por TC nos demais egressos,
conforme o P1 corrigido. A0/A1 e F02–F05 não são
alterados; não há pre-shaping, CBS ou TAS. `TrafficCatalog` permanece como
validação do catálogo, separada dos resultados de C0.
`catalog-bindings.ini` substitui o configurador MAC automático por entradas
estáticas com VLAN; o configurador automático permanece na topologia sem tráfego.

`C1_source_preshaping.ini` estende C0 sem alterar topologia, fluxos, VLAN, PCP,
rotas, filas ou serviço SP. Para cada imagem, emite os 30 pacotes individualmente
com δ=min(324 µs,C/30) em F02/F03 e δ=min(500 µs,C/30) em F04/F05.
`Validate_C1_Lx_Ay` usa seed 41, 1 s de warm-up, 30 s de medição e 50 ms de
drenagem, coletando latência, ocupação, tempo em fila, utilização nos 56
transmissores e descartes.
Execute `python3 scripts/run/validate_c1.py --jobs 4`; os resultados ficam em
`simulations/results/C1/p1-validation-64KiB/`; a comparação pareada com C0 é
`C0_C1_comparison.json`. Os resultados antigos de C1, com câmeras em 32 KiB,
permanecem preservados em `p1-validation/`. A matriz final de 64 KiB foi
validada e pareada com C0 na seed 41: 8/8 células viáveis, zero drops e geração
de frames idêntica ao baseline. Uma execução intermediária que truncava a última
imagem está preservada em `p1-validation-64KiB-truncated-shaper-diagnostic/`;
ela não compõe o relatório final. Para retomar uma matriz
interrompida e reutilizar relatórios e resultados
brutos completos, use `python3 scripts/run/validate_c1.py --jobs 4 --resume`.

Depois de editar o CSV, executar `python3 scripts/catalog/generate.py` na raiz.

## C2 — CBS nominal

`C2_nominal_cbs.ini` estende C0. Portanto, conserva a classificação PCP→TC,
SP nas classes sem CBS, os buffers drop-tail e os bursts originais de câmera;
não aplica pre-shaping. O único tratamento acrescentado são os algoritmos
INET `Ieee8021qCreditBasedShaper` nas classes TC6/SR-A e TC4/SR-B dos egressos
que carregam tráfego permanente dessas classes.

`scripts/catalog/generate_cbs.py` deriva `idleSlope` pela soma das taxas wire
permanentes (`R_wire`) do catálogo em cada par egress/classe. Os fluxos
escaláveis são multiplicados pelos fatores L0–L3 (0,5/1/2,5/4); F21/F22 usam
TC6 quando ativos, mas são transientes e ficam fora da reserva. No multicast
F14, cada porta comum é contada uma vez e os egressos de ramificação recebem a
taxa encaminhada por eles. O P1 não aplica ao C2 o teto de admissão de 75% usado
na calibração de C3/C4. Portas sem tráfego permanente de uma classe não recebem
CBS com `idleSlope=0`; assim não se inventa reserva para fluxos exclusivamente
transientes.

Gere e confira os artefatos com:

```bash
python3 scripts/catalog/generate_cbs.py
python3 scripts/catalog/generate_cbs.py --check
```

As oito configurações `Validate_C2_Lx_Ay` usam seed 41 e as mesmas janelas,
buffers e métricas de C0/C1. `scripts/run/validate_c2.py` compara os resultados
pareados e audita a instância e o `idleSlope` de cada CBS, vetores e resumos
min/max/time-average de crédito, eventos transientes, latência, misses, perdas,
goodput e filas. O P1 §5.4 trata crédito CBS como métrica explicativa, quando
necessária, e não como gate primário de viabilidade. O validador reativa via
linha de comando o vetor `numCredits`, que a configuração-base desativa; as
séries disponíveis são anexadas ao JSON, sem invalidar uma célula que contenha
as métricas primárias completas. Um smoke curto confirmou 25 vetores e resumos
numéricos em L0/A0. A matriz completa foi executada e auditada: C0/C1/C2 tiveram
1/8, 8/8 e 0/8 células viáveis, respectivamente. Todas as células C2 foram
reprovadas pelo gate por misses e/ou perdas; nenhuma fila apresentou
crescimento sustentado. Nas células L0/L1, ainda havia 459/450/274/267 pacotes
enfileirados no término, separados de drops e reconciliados com `queueLength:last`
no SCA. Isso explica por que o relatório mantém contagens de drops distintas
das entregas pendentes. O comparativo final está em
`simulations/results/C2/p1-validation-64KiB-final/`, nos arquivos
`C0_C1_C2_comparison.json` e `C0_C1_C2_analysis.md`. A pasta anterior
`p1-validation-64KiB/` contém a execução interrompida/concorrente e não é a
fonte do comparativo final.
