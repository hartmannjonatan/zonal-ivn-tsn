# Validação incremental do benchmark P1

`topology/` contém a validação executável da topologia P1: configuração de
sondas ICMP, verificador dos resultados e guia de inspeção Qtenv. `traffic/`
contém o verificador dos 22 fluxos, da matriz L/A, do multicast e dos transientes.
`classification/` valida o C0 completo no benchmark, inclusive nos talkers.
`source_preshaping/`, `cbs/`, `tas/` e `integration/` continuam reservadas às
próximas etapas. Os microcenários INET existentes permanecem em
`simulations/tsn_validation/`.

| Etapa/pasta | Critério de aceitação |
|---|---|
| topology — concluída | Links LC/LB/LP/LA, caminhos estáticos e CPU fora do trânsito; ramificação física para F14 pronta |
| traffic — concluída | F01–F22, tamanhos/camadas, taxas, offsets, L0–L3 e A0/A1 |
| classification — C0 concluído | As oito células P1 de 30 s validaram 42 egressos/336 filas cada; zero filas com crescimento contínuo. Resultado 0/8 viáveis com F01/F06/F07 tratados como hard-critical: perdas de 30% em F02–F05 e misses hard de F01/F06/F07 em células de maior contenção. Evidência: `classification/c0-p1-results.md` |
| source_preshaping | C1 muda apenas a liberação de F02–F05 |
| cbs | C2 nominal, C3 calibrado, crédito e limite de reserva por porta |
| tas | Sete egressos, GCL, serviço CBS efetivo e offsets gPTP |
| integration | Piloto C0–C4 em L2/A1, métricas completas e filas estáveis |

O C0 está pronto como baseline auditado para iniciar C1, que deve aplicar
pre-shaping apenas a F02–F05 e reexecutar a mesma matriz. Seeds de
validação/calibração/piloto devem ser separados de 1001–1030.
Não transportar os parâmetros simplificados dos microcenários diretamente ao benchmark.
