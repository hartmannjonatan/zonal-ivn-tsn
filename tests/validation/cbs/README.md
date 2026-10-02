# Validação CBS — C2 nominal

C2 mantém topologia, carga, filas e comportamento de C0, acrescentando o
`Ieee8021qCreditBasedShaper` do INET 4.7 às classes SR-A/TC6 e SR-B/TC4 nos
egressos com tráfego permanente reservado. Não aplica pacing na origem: os
bursts de 30 frames das câmeras permanecem intactos.

## Reservas

O gerador `scripts/catalog/generate_cbs.py` lê `simulations/zonal/traffic/flows.csv`
e aplica a rota estática de cada fluxo para somar `R_wire` em cada egress/classe.
Fluxos escaláveis acompanham o fator de carga L; F21/F22 são excluídos da
reserva porque são transientes. F14 é multicast: a taxa é somada uma vez nos
egressos compartilhados e nas portas de ramificação. C2 não usa o teto de 75%
reservado pelo P1 às calibrações C3/C4.

Os artefatos gerados são `simulations/zonal/configs/mechanisms/C2_nominal_rates.ini`
e `simulations/zonal/traffic/cbs_nominal_reservations.csv`. Regerar e verificar:

```bash
python3 scripts/catalog/generate_cbs.py
python3 scripts/catalog/generate_cbs.py --check
```

## Execução e aceitação

Com OMNeT++ e INET carregados, execute a matriz pareada com C0/C1:

```bash
python3 scripts/run/validate_c2.py --inet-root "$INET_ROOT" \
  --omnetpp-root "$OMNETPP_ROOT" --jobs 2 --resume
```

O validador confere para cada célula L0–L3 × A0/A1 a presença exata dos
algoritmos CBS e o `idleSlope` resolvido, além da igualdade dos eventos F21/F22
sob seed 41 e métricas por fluxo/receptor. A aceitação inclui
deadlines (conclusão de imagem nas câmeras), perda, goodput, latência, filas e
estabilidade. O P1 §5.4 classifica crédito CBS como métrica explicativa,
coletada quando necessária para interpretar o comportamento, e não como gate
primário de viabilidade. O validador reativa pela linha de comando o vetor
`numCredits`, desativado globalmente pela configuração-base; o relatório marca
a disponibilidade dos vetores por célula. Um smoke L0/A0 confirmou os 25 vetores
esperados e seus resumos min/max/time-average. A matriz seed 41 foi concluída:
C2 passou 0/8 gates de viabilidade, comparado a C0 1/8 e C1 8/8. As oito células
foram simuladas e tiveram suas configurações, filas e métricas primárias
auditadas; crédito explicativo foi gravado em 6/8, sem afetar o gate. Drops
ocorreram sob CBS nominal mesmo com zero filas de crescimento sustentado. Em
L0/L1 sobraram 459, 450, 274 e 267 pacotes nas filas ao final da drenagem; são
pendentes, reconciliados com `queueLength:last`, e não drops por overflow. A
perda no receptor continua refletindo tráfego não entregue dentro da janela.
Resultados brutos, JSON e análise Markdown ficam em
`simulations/results/C2/p1-validation-64KiB-final/`; a comparação pareada é
`C0_C1_C2_comparison.json` e `C0_C1_C2_analysis.md`.
O diagnóstico adicional, reprocessado exclusivamente dos `.sca`, `.vec` e CSVs
existentes, está em `C0_C1_C2_diagnostic.json` e
`C0_C1_C2_diagnostic.md`. Ele reconcilia drops por fila/fluxo e escopo temporal,
taxas de TC6/TC4, ocupação e pacotes pendentes; as limitações de timestamp dos
CSVs são declaradas no relatório. Para regenerá-lo dos vetores brutos, use
`python3 scripts/run/diagnose_c2.py` (leitura longa, sem executar simulações);
`--reuse-extracted` só remonta o relatório a partir da extração JSON existente.
O resumo do smoke de créditos está em
`simulations/results/C2/cbs-credit-smoke2/cbs-credit-summary.json` e não é
misturado à matriz medida de 30 s.

Uma seed de validação caracteriza o mecanismo, mas não substitui a campanha
estatística final com seeds 1001–1030. C2 contra C0 mede o efeito de adicionar
CBS nominal ao SP; C2 contra C1 contrasta CBS com o pre-shaping de origem. H3
depende da comparação posterior C3−C2.
