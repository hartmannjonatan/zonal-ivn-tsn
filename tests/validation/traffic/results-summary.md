# Evidências da consolidação — 2026-09-29

Ambiente: OMNeT++ 6.4.0, INET 4.7.0. Os dez conjuntos de resultados locais
foram reanalisados pelo verificador independente do catálogo, com aprovação
dos checks de emissões, tamanhos, VLAN/PCP, caminhos, multicast e transientes.

| Execução | Pacotes gerados nas origens | Descartes registrados |
|---|---:|---:|
| ValidateReseed-0 | 192536 | 0 |
| ValidateSignatures-0 | 37860 | 0 |
| Validate_L0_A0-0 | 154518 | 0 |
| Validate_L0_A1-0 | 154548 | 0 |
| Validate_L1_A0-0 | 194669 | 0 |
| Validate_L1_A1-0 | 194729 | 0 |
| Validate_L2_A0-0 | 315122 | 0 |
| Validate_L2_A1-0 | 315152 | 0 |
| Validate_L3_A0-0 | 435575 | 0 |
| Validate_L3_A1-0 | 435575 | 0 |

Total: 2,430,284 pacotes gerados, incluindo warm-up.

As oito células L/A usam 40 ms de warm-up e 2 s medidos. ValidateReseed usa
outra seed; ValidateSignatures cobre as dez assinaturas de cada transiente
em 10 s. O pareamento confirmou as mesmas escolhas aleatórias entre células
L/A e mudança com a seed alternativa. Diferenças de 30 pacotes entre A0/A1
refletem as fases das câmeras na borda da janela finita.

F14 percorreu LC uma vez por sequência, com replicação no CSW somente para
os dois displays. F21/F22 conservaram os volumes de aplicação, incluindo os
segmentos finais, com MTU IPv4 de 1500 B e overhead IP/UDP contabilizado.

Aprovação do catálogo não significa cumprimento de todos os deadlines:
por exemplo, L3/A1 apresentou misses em F01, F06 e F07. As estatísticas
consideram a coorte gerada na janela medida. O suporte atual usa prioridade
estrita e buffers por classe nos switches; as origens mantêm staging FIFO.
Isso não constitui validação dos tratamentos completos C0–C4 nem substitui
a campanha de 30 s, repetições estatísticas ou inspeção visual no Qtenv.

Os CSVs, logs e validation.json completos permanecem em
`simulations/results/traffic/` (ignorados pelo Git). Para reproduzir ou
reanalisar, seguir o [README da validação](README.md).

Na consolidação, o script de build também concluiu com sucesso e L3/A1 foi
executado novamente pelo launcher corrigido: término normal em 2,09 s,
435.575 pacotes e zero descartes, com aprovação do verificador. Um teste
negativo em cópia temporária das evidências adicionou uma ramificação indevida
de F14 para CSW.eth3; o verificador rejeitou esse egresso extra.
