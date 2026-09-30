# Validação incremental do benchmark P1

`topology/` contém a validação executável da topologia P1: configuração de
sondas ICMP, verificador dos resultados e guia de inspeção Qtenv. `traffic/`
contém o verificador dos 22 fluxos, da matriz L/A, do multicast e dos transientes.
As demais pastas continuam reservadas às próximas etapas.
Os microcenários INET existentes permanecem em `simulations/tsn_validation/`.

| Etapa/pasta | Critério de aceitação |
|---|---|
| topology — concluída | Links LC/LB/LP/LA, caminhos estáticos e CPU fora do trânsito; ramificação física para F14 pronta |
| traffic — concluída | F01–F22, tamanhos/camadas, taxas, offsets, L0–L3 e A0/A1 |
| classification | VLAN/PCP→TC, SP, buffers finitos e drops |
| source_preshaping | C1 muda apenas a liberação de F02–F05 |
| cbs | C2 nominal, C3 calibrado, crédito e limite de reserva por porta |
| tas | Sete egressos, GCL, serviço CBS efetivo e offsets gPTP |
| integration | Piloto C0–C4 em L2/A1, métricas completas e filas estáveis |

Seeds de validação/calibração/piloto devem ser separados de 1001–1030.
Não transportar os parâmetros simplificados dos microcenários diretamente ao benchmark.
