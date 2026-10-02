# Validação incremental do benchmark P1

`topology/` contém a validação executável da topologia P1: configuração de
sondas ICMP, verificador dos resultados e guia de inspeção Qtenv. `traffic/`
contém o verificador dos 22 fluxos, da matriz L/A, do multicast e dos transientes.
`classification/` valida o C0 completo, `source_preshaping/` valida C1 e `cbs/`
valida C2 nominal. `tas/` e `integration/` ficam reservadas às próximas etapas. Os
microcenários INET existentes permanecem em `simulations/tsn_validation/`.

| Etapa/pasta | Critério de aceitação |
|---|---|
| topology — concluída | Links LC/LB/LP/LA, caminhos estáticos e CPU fora do trânsito; ramificação física para F14 pronta |
| traffic — concluída | F01–F22, tamanhos/camadas, taxas, offsets, L0–L3 e A0/A1 |
| classification — C0 com 64 KiB validado | Matriz seed 41 completa; 0 drops, zero overflow CAM, frames completos e filas estáveis; 1/8 células viáveis após aplicar F01/F06/F07 como `high-hard`. Relatórios em `simulations/results/C0/p1-validation-64KiB/` |
| source_preshaping — C1 com 64 KiB validado | Matriz seed 41 completa; 8/8 células viáveis, 0 drops e frame counts iguais ao C0. Análise pareada em `simulations/results/C1/p1-validation-64KiB/C0_C1_analysis.md` e dados por fluxo no JSON adjacente |
| cbs — C2 nominal validado | Matriz seed 41 completa; CBS em TC6/SR-A e TC4/SR-B, reservas por egress derivadas de `R_wire`, F21/F22 excluídos; 0/8 células viáveis (C0: 1/8, C1: 8/8). Nenhuma fila teve crescimento sustentado; crédito explicativo disponível em 6/8 células |
| cbs futuro | C3 calibrado em L2/A1, razões congeladas e limite de reserva por porta |
| tas | Sete egressos, GCL, serviço CBS efetivo e offsets gPTP |
| integration | Piloto C0–C4 em L2/A1, métricas completas e filas estáveis |

O baseline corrigido foi fechado nas oito células C0/C1, pareadas pela seed 41.
Os drops são zero nas câmeras e na rede; a não viabilidade remanescente de C0
decorre de deadline misses, não de perda de pacotes. C1 aplica pre-shaping
apenas a F02–F05. O catálogo canônico já
rotula F01/F06/F07 como `high-hard`. Seeds de validação/calibração/piloto devem
ser separados de 1001–1030.
Não transportar os parâmetros simplificados dos microcenários diretamente ao benchmark.

O procedimento, os artefatos de reserva e o relatório comparativo C0/C1/C2
estão em `simulations/zonal/configs/README.md` e
`simulations/results/C2/p1-validation-64KiB-final/`. Pacotes ainda enfileirados
ao fim da drenagem são reportados como pendentes, verificados contra a ocupação
final das filas e mantidos distintos dos drops; a falta de entrega até o fim da
janela continua contando para perda/miss nos critérios de recepção.

## Auditoria de percentis e janelas

`validate_c0.py` calcula p99 empírico por nearest-rank com uma cauda de tamanho
fixo derivada da população medida. A população de latência por pacote é
selecionada pelo instante `CreationTimeTag`, e a população de conclusão de
imagem pela disponibilidade do ciclo; ambas podem ser recebidas até o fim da
drenagem. Os vetores OMNeT++ são reconciliados com contagens, máximo e misses
dos CSVs. A métrica por pacote (`recepção − liberação do pacote`) permanece
distinta da métrica de câmera (`último frame − disponibilidade da imagem`), que
inclui o espaçamento do pre-shaping e determina o gate de deadline F02–F05.

A auditoria do comparativo encontrou que a capacidade do heap de p99 crescia
durante a leitura do vetor. Como as amostras estavam ordenadas no tempo, valores
antigos de baixa latência permaneciam na cauda, subestimando p99 embora misses
e máximos estivessem corretos. O cálculo foi corrigido para capacidade fixa;
os relatórios de C0/C1 são regenerados com essa correção.
