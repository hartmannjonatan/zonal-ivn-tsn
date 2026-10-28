# Plano de evidências visuais para o ICIT

Não gerei figuras finais nesta etapa. Recomendo três elementos principais, nesta ordem.

1. **Matriz de aprovação e cobertura** — tabela/heatmap com papel C0–C3 nas linhas e carga×alinhamento nas colunas. Mostrar `aprovadas/incluídas` e `incluídas/planejadas` dentro de cada célula. C2 (artigo; diretório histórico C3) tem L3 rejeitado pelo limite de reservas; C3 (artigo; diretório histórico C4) tem L3 rejeitado na triagem de serviço. C3 parcial deve aparecer como parcial, jamais como 30/30. Inclua n, seeds e legenda distinta para não executado, pendente e inadmissível. Indispensável.

2. **Entrega de imagens versus perdas e latência** — dois painéis para F02/F05 em C0/C1, focados em L3/A0 e L3/A1: barras empilhadas de imagens completas/incompletas (denominador imagens oferecidas) mais ponto/intervalo da mediana por execução do p99 de conclusão apenas entre completas; anotar o deadline aplicável. Evitar eixo comum que esconda incompletude; marcar que p99 é condicional. Não converter pacotes perdidos em imagens sem correspondência de coorte. Apresentar 30 execuções como n=30, sem intervalos construídos por pacotes. Indispensável.

3. **Latência de fluxos críticos e custo do C3 combinado** — pontos por execução para F06/F07, F08–F10 em células selecionadas C2/C3; eixo y em µs, linhas de deadline (100 µs para os fluxos hard pertinentes), mediana e faixa entre execuções. Descrever C3−C2 como políticas completas. Como C3 atual é L0 completo e L1/L2 parcial, não desenhar células pendentes como zero; mostrar n ao lado de cada grupo. Complementar/indispensável conforme espaço.

Reservas configuradas podem aparecer numa tabela compacta de método (idleSlope por porta/TC, soma por porta e margem ao limite), não num scatter que implique consumo físico agregado entre saltos. Separar sincronização amostral de contínua.
