# Validação do C1 — pre-shaping de origem

C1 estende o C0 e altera apenas a cadência de liberação de F02–F05. Topologia,
fluxos e tamanhos do catálogo, VLAN, PCP, deadlines, destinos, rotas, filas,
capacidades drop-tail, gates sempre abertos e serviço SP permanecem iguais.
Conforme o P1 corrigido, câmeras usam 64 KiB por classe; G1–G4 mantêm 128 KiB e
os demais egressos, 32 KiB.

Para cada imagem de 30 pacotes, as câmeras emitem um pacote individual a cada
δ=min(324 µs,C/30) para F02/F03 (ADAS), ou δ=min(500 µs,C/30) para F04/F05
(vision). C é o período de quadro depois da escala L0–L3. O ciclo, a quantidade
e o tamanho dos pacotes e o primeiro instante da imagem são preservados. A0/A1
continuam definindo a fase inicial conforme o catálogo. Se o ciclo da imagem
começa antes do fim da janela de medição, o pre-shaper emite seus 30 frames
completos; os frames finais podem cair nos 50 ms de drenagem. Eles não entram
na população de latência individual se liberados depois do fim da medição, mas
contam para concluir a imagem iniciada dentro da janela. Assim, o shaping altera
o espaçamento sem truncar o volume oferecido e mantém a contagem de frames
pareada com C0. Fila egressa drop-tail
continua ativa, portanto o mecanismo não remove os limites físicos do link nem
reclassifica perdas como sucesso.

As métricas distinguem a latência individual (`recepção − CreationTimeTag`)
da conclusão da imagem (`último dos 30 frames − disponibilidade do ciclo`).
Pacotes da cauda liberados durante a drenagem não pertencem ao cohort de
latência individual `[warm-up,fim)`, mas completam a métrica de imagem quando a
disponibilidade ocorreu dentro dessa janela. Imagens incompletas entram como
misses no gate, usando como denominador as disponibilidades previstas pelo
catálogo.

## Executar

Com OMNeT++ 6.4.0 carregado e `INET_ROOT` apontando para INET 4.7.0:

```bash
bash scripts/run/build.sh
python3 scripts/run/validate_c1.py --jobs 4
```

O validador verifica primeiro se CSV, XML e bindings gerados correspondem ao
catálogo. Em seguida executa `Validate_C1_L0_A0` a `Validate_C1_L3_A1`, seed 41,
1 s de warm-up, 30 s de medição e 50 ms de drenagem. A seed é pareada à
referência C0 para manter iguais as assinaturas sorteadas de F21/F22.

Cada célula passa pela auditoria do catálogo (emissões e espaçamentos, payloads,
VLAN/PCP, caminhos, multicast e conservação por salto), pela verificação dos
42 egressos com classe e 336 filas, dos 56 transmissores físicos e pela coleta
das métricas P1: latência por receptor
(p99/máximo), misses incluindo perda, goodput, perdas, ocupação em seis janelas
de 5 s, estabilidade, histogramas de tempo em fila e utilização, além de
descartes timestamped por fila durante a medição. Os resultados ficam em
`simulations/results/C1/p1-validation-64KiB/`, ignorados pelo Git; o consolidado é
`C1_acceptance.json`. Se a avaliação C0 consolidada estiver disponível, o script escreve
`C0_C1_comparison.json`, pareando as mesmas células e fluxos para throughput
útil, misses, goodput, perdas e latências p99/máxima. Para recalcular as métricas a partir dos resultados brutos sem repetir as
simulações, execute `python3 scripts/run/validate_c1.py --reassess-existing`.
Para regenerar apenas a comparação a partir dos JSONs, use
`python3 scripts/run/validate_c1.py --compare-existing`. Para retomar uma matriz
interrompida, `--resume` reutiliza células que já têm resultado e relatório
completos, executando ou reavaliando apenas as demais.

O p99 usa nearest-rank com heap de cauda de tamanho fixo derivado da população
medida. A janela é selecionada pelo timestamp de origem (`CreationTimeTag` ou
disponibilidade da imagem), não pelo tempo de recepção. Essa regra corrige a
subestimação do heap anterior, cuja capacidade crescia conforme o vetor era
lido em ordem temporal.

Uma célula não viável continua sendo evidência válida do tratamento. O gate
marca F01, F06 e F07 como `high-hard`, conforme o catálogo atualizado. A
campanha final de 30 seeds 1001–1030 só ocorre depois do piloto e do
congelamento do protocolo.

## Resultado seed 41

Os resultados C1 da configuração anterior, com talkers de câmera de 32 KiB,
permanecem em `p1-validation/` como registro histórico. A primeira execução com
64 KiB revelou truncagem da última imagem quando seu ciclo começava antes do fim
da janela; foi preservada em `p1-validation-64KiB-truncated-shaper-diagnostic/`
e não é usada na comparação final. O agendamento e o checker foram corrigidos
para completar os 30 frames iniciados antes do limite. A matriz final seed 41
está em `p1-validation-64KiB/` e está pareada com C0.

Resultado final: 8/8 células C1 viáveis, zero overflow nas filas de câmera,
zero drops em todas as filas da rede e contagens F02–F05 idênticas às de C0 em
cada célula. Os bursts completos contabilizados por fluxo/célula estão no
`validation.json` de cada execução. O comparativo detalhado de latência p99 e
máxima, deadline misses, perdas, goodput e filas está em
[`C0_C1_comparison.json`](../../../simulations/results/C1/p1-validation-64KiB/C0_C1_comparison.json)
e a leitura de H1/H2 em
[`C0_C1_analysis.md`](../../../simulations/results/C1/p1-validation-64KiB/C0_C1_analysis.md).
Essa validação de seed 41 não substitui as 30 repetições da campanha final.

O checker reproduz a quantização de 1 ps do `SimTime` para os instantes
calculados por `C/30`, e confere que cada ciclo iniciado antes do fim da janela
gera os 30 frames, inclusive quando a cauda do burst termina durante a drenagem.
