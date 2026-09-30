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
| mechanisms/C1–C4 | Contratos das próximas configurações |
| synchronization.ini | Contrato gPTP para a etapa C4 |

`TopologyValidation` é a rede sem aplicações; `TopologyConnectivity` usa ICMP;
`SmokeTest` continua como alias. `Traffic_Lx_Ay` valida o catálogo sob seu suporte,
enquanto `C0_Lx_Ay` aplica o baseline P1 de prioridade estrita. C0 ativa filas
classificadas também nos talkers, com gates sempre abertos, SP TC7→TC0 e filas
drop-tail finitas por classe. As validações `Validate_C0_Lx_Ay` usam a mesma
configuração de filas por 1 s de warm-up, 30 s de medição e 50 ms de drenagem,
coletando latência e ocupação por classe para a análise de estabilidade. As
configurações C0 de campanha usam 1 s de warm-up,
30 s de medição e 50 ms de drenagem. A auditoria seed 41 concluiu as oito
células: as filas estão corretamente classificadas e configuradas, não há
crescimento persistente, mas F02–F05 perdem 30% nos egressos das câmeras; o
resumo está em `tests/validation/classification/c0-p1-results.md`. O gate de
deadline também trata F01/F06/F07 como hard-critical por decisão da análise; essa
regra não altera o CSV do catálogo.
`Validate_Lx_Ay` usa 40 ms de warm-up e
2 s medidos; `ValidateReseed` verifica seed diferente. `ValidateSignatures`
percorre deterministicamente todas as assinaturas, somente com F21/F22.

`C0_strict_priority.ini` determina buffers de 128 KiB por TC nos egressos G1–G4
e 32 KiB por TC nos demais egressos, conforme o P1. A0/A1 e F02–F05 não são
alterados; não há pre-shaping, CBS ou TAS. `TrafficCatalog` permanece como
validação do catálogo, separada dos resultados de C0.
`catalog-bindings.ini` substitui o configurador MAC automático por entradas
estáticas com VLAN; o configurador automático permanece na topologia sem tráfego.

Depois de editar o CSV, executar `python3 scripts/catalog/generate.py` na raiz.
