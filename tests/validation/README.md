# Validação incremental do benchmark P1

Estas pastas são reservas estruturais e ainda não contêm testes executáveis.
Os microcenários INET existentes permanecem em `simulations/tsn_validation/`.

| Etapa/pasta | Critério de aceitação |
|---|---|
| topology | Links LC/LB/LP/LA, caminhos estáticos, CPU fora do trânsito e multicast F14 |
| traffic | F01–F22, tamanhos/camadas, taxas, offsets, L0–L3 e A0/A1 |
| classification | VLAN/PCP→TC, SP, buffers finitos e drops |
| source_preshaping | C1 muda apenas a liberação de F02–F05 |
| cbs | C2 nominal, C3 calibrado, crédito e limite de reserva por porta |
| tas | Sete egressos, GCL, serviço CBS efetivo e offsets gPTP |
| integration | Piloto C0–C4 em L2/A1, métricas completas e filas estáveis |

Seeds de validação/calibração/piloto devem ser separados de 1001–1030.
Não transportar os parâmetros simplificados dos microcenários diretamente ao benchmark.
