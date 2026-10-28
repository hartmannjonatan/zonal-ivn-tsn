# Síntese editorial dos resultados para o IEEE ICIT 2027

**Recomendação:** mantenha o artigo como estudo experimental aplicado de TSN para comunicação automotiva/zonal, mas concentre a narrativa principal no efeito observado de alinhamento e pre-shaping sobre entrega de câmeras e no limite de transferibilidade da política CBS escalada. Apresente o tratamento combinado CBS/TAS como evidência promissora ainda parcial, não como validação abrangente ou melhoria causal atribuível a TAS. O tema se encaixa no ICIT por sistemas de comunicação industrial, redes de controle e transporte/automotivo; o encaixe depende de enfatizar requisitos de comunicação de um sistema ciberfísico veicular, não de alegar novidade de mecanismos.

**Corte:** 2026-10-27T16:43:14-03:00 (fuso registrado nos artefatos). C4 foi congelado pelo ledger/checkpoint em 90 execuções concluídas válidas de 180 posições L0–L2; somente as 90 linhas concluídas com hashes de relatório conferidos entram nesta síntese. Não usei dados de uma execução ativa/incompleta. O estado do checkpoint no corte é `paused_technical_review`, com C4_L1_A0_seed1022 como falha técnica posterior à cobertura incluída.

## Correspondência dos tratamentos

| Nome editorial no manuscrito | Identificador histórico | Interpretação |
|---|---|---|
| C0 — Strict Priority | `C0` | SP; rajadas originais |
| C1 — Source pre-shaping | `C1` | pré-formação na fonte |
| C2 — Calibrated CBS | `C3` | CBS calibrado; não confundir com o CBS nominal histórico |
| C3 — Joint CBS/TAS configuration | `C4` | perfil absoluto D3, gates TAS compartilhadas e SP nas saídas exclusivas dos freios |

Não renomeei diretórios ou registros. Pilotos não foram somados às repetições oficiais.

## Cobertura e validade

A matriz cobre 28 células admissíveis × 30 execuções = 840 posições planejadas: C0 240/240; C1 240/240; C2 180/180 (L3/A0 e L3/A1 rejeitadas antes de simular pela triagem CBS); C3 90/180 (somente L0 completo, L1/L2 parciais). Das 750 execuções incluídas, 599 passaram os gates do tratamento e 151 foram reprovações válidas de desempenho: C0 210/240, C1 240/240, C2 59/180, C3 90/90 no recorte disponível. A contagem não extrapola aprovação a posições pendentes.

| Tratamento editorial | L0/A0 | L0/A1 | L1/A0 | L1/A1 | L2/A0 | L2/A1 | L3/A0 | L3/A1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 0/30 |
| C1 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 | 30/30 |
| C2 (hist. C3) | 0/30 | 0/30 | 0/30 | 0/30 | 30/30 | 29/30 | inadmissível | inadmissível |
| C3 (hist. C4) | 30/30 | 30/30 | 21/21 | 3/3 | 3/3 | 3/3 | inadmissível | inadmissível |

C3 seeds em L1/A0 são 1001–1021; L1/A1, L2/A0 e L2/A1 usam 1001, 1015 e 1030. C3 L3 foi rejeitado na triagem de serviço do perfil absoluto, não por ultrapassar o teto de 75% de reserva. A matriz integral está em [coverage_editorial.csv](coverage_editorial.csv).

## Achados essenciais

**1. Alinhamento expõe uma fronteira de falha de SP em L3.** Em C0, L3/A0 passou 30/30, enquanto L3/A1 passou 0/30. Para A1, os relatórios registram 579.892 perdas no receptor, localizadas em CSW→HPC/TC4; F02 perdeu 219.747 de 6.750.000 pacotes (3,26%) e 219.565 das 225.000 imagens ficaram incompletas (97,58%). Isso é evidência forte para este benchmark e célula, não uma lei geral sobre tráfego alinhado.

**2. Pre-shaping recupera a entrega integral, com custo de latência de conclusão.** Em C1 L3/A1, 30/30 passaram; F02 e F05 receberam todos os 6.750.000 pacotes por fluxo, e as 225.000 imagens por fluxo foram completas. Em C0, F05 perdeu 360.145 pacotes e teve 186.094 imagens incompletas. Para F02, o total de pacotes perdidos excede as imagens incompletas em 182; a proximidade dos agregados não permite inferir quais pacotes pertenciam a quais imagens nem a distribuição das perdas por imagem sem rastreamento individual. Em baixa carga L0/A0, o p99 mediano de conclusão de imagem subiu em C1 versus C0 em 8,978 ms para F02 e 14,134 ms para F04 (pareado, n=30); ambos ainda dentro dos deadlines publicados para esses fluxos. Em L3/A1, o p99 calculado só entre imagens completas é condicionado aos sobreviventes, portanto não compara atendimento completo sem a taxa de incompletude. C0/C1 também têm diferença de binário/replay; assinaturas dos calendários e populações F21/F22 coincidem, mas isso limita uma atribuição causal estrita.

**3. CBS calibrado por carga falha na baixa carga, mas funciona quase sempre em L2.** O tratamento C2 (histórico C3) passa 0/120 em L0/L1 e 59/60 em L2; a reprovação restante é estabilidade em L2/A1, sem perda de aplicação. Em L0/L1 há perdas/overflow TC4 e reprovações de estabilidade; na comparação pareada C2−C0 tem 180/180 assinaturas de calendário iguais; em L0/A0, p99 medianos de F06/F07 sob C2 são 213,39/219,17 µs contra 30,08/25,08 µs em C0 (diferenças +183,32/+194,09 µs), sem perdas desses sensores. Em L0/L1, no conjunto das 120 execuções low-load, foram reportadas 7.396.671 perdas de medição em TC4: Z2 uplink 3.226.611, Z1 uplink 2.927.874 e CSW→Z3 1.242.186. Separadamente, F06/F07 excedem deadline hard de 100 µs mesmo sem perdas: em L0/A0 os p99 medianos são 213,39/219,17 µs; em L2/A0, 58,94/53,97 µs. A política escala reservas com demanda permanente, enquanto os transientes F21/F22 e deadlines/tamanhos não escalam; isso é compatível com as falhas, mas os dados não isolam causalmente a escala como único mecanismo. Não há comparador oficial de CBS nominal neste artigo.

**4. O resultado oficial atual de CBS/TAS é positivo, porém incompleto e com custo de cauda dos freios.** As 90 execuções concluídas de C3 (histórico C4) passam todas os gates de aplicação, estabilidade e sincronização amostral, sem perdas de receptor reportadas. L0 está completo (60/60); L1 tem 24/60 e L2 6/60. O máximo observado de latência dos freios foi 78,461 µs para deadline 100 µs (margem observada mínima 21,539 µs). Em pares comuns de L0/A0 com C2, p99 aumenta medianamente 57,594 µs (F08), 57,996 µs (F09) e 57,587 µs (F10), ainda sem perder o deadline. Como perfil CBS, sincronização e TAS diferem, isto é comparação de políticas completas. A sincronização é aprovada nas amostras: cada execução tem 184.800–184.820 amostras por nó na janela [1,31), com máximo absoluto de 50 ns entre nós e zero amostras acima de 1 µs; conformidade contínua não foi verificada. A série compacta está em [c4_clock_samples.csv](c4_clock_samples.csv).

Os achados, tabelas e dados por execução estão em `key_findings.csv`, `selected_run_metrics.csv`, `selected_paired_metrics.csv` e `camera_image_summary.csv`. A unidade experimental é a execução; milhões de pacotes não são tratados como réplicas independentes. A tabela compacta completa de idleSlopes, totais por egress e margens até 75% está em [reservation_profiles.csv](reservation_profiles.csv); os totais são reservas configuradas em cada porta, não tráfego utilizado nem banda somável entre saltos. Por exemplo, em `HPC.eth[0]/TC4`, o perfil escalado C2 vai de 78,24 Mb/s (L0) a 144 Mb/s (L2), enquanto C3 fixa 406,375399 Mb/s; em `CSW.eth[3]/TC4`, C2 vai de 49,52 a 247,60 Mb/s, enquanto C3 fixa 707,606774 Mb/s. C3 reserva 70,76% da porta CSW.eth[3], ainda abaixo do limite de 75%, com 42,393 Mb/s de headroom configurável.

## Pareamento, software e consistência dos relatórios

Calendários e populações pareiam exatamente nos contrastes disponíveis: C0/C1 240/240 pares e 480/480 verificações F21/F22; C0/C2 180/180 pares e 360/360 verificações F21/F22; C1/C2 180/180; C2/C3 90/90 no recorte C4, com F21/F22 iguais em todos os testes auditados. A comparação C2/C3 continua sendo de políticas completas.

C0 usa binário SHA-256 `68207064…ffc074`; C1 e C2 usam `ca8e9d75…ba32a7`. A diferença inclui a implementação de replay de calendário em `TrafficPlan.cc/.ned`; eventos gravados e populações pareadas reduzem a preocupação sobre o calendário aplicado, mas a diferença de software continua sendo uma limitação de C1−C0. O histórico dos primeiros 210 relatórios C0 não preserva todos os hashes de fonte do runner/extrator. Não descartei dados por diferença de hash isolada.

Os 180 relatórios de C2 (histórico C3) têm perfil resolvido verificado, arquivos de validação, logs e SCA, com `simulated_in_this_attempt` em 176 e `reprocessed_existing_completed_raw_output` em quatro. Há, porém, divergência no fechamento: o shard manifest declara `all_records_technically_valid=false`/`incomplete_resumable` e seu campo de hash do ledger não corresponde a um ledger específico de 180 linhas; o ledger principal tem 447 registros incluindo tentativas de calibração. O `campaign_results.json` e os campos `treatment`/`campaign_treatment` também não usam a mesma nomenclatura. Assim, o conjunto de resultados por execução é corroborado, mas o fechamento canônico não é perfeitamente reconciliado. Isso afeta a afirmação de encerramento formal e a reprodutibilidade de proveniência, não os números relatados individualmente que têm artefatos de validação.

O critério de estabilidade é operacional: seis médias temporais ponderadas de ocupação em bits para janelas consecutivas de 5 s dentro de [1,31) s; falha se as três últimas crescem estritamente (`q4<q5<q6`) e `q6−q4>0,05×capacidade` em qualquer fila. É um gate finito da campanha, não prova de estabilidade assintótica. Warm-up é excluído da janela de perdas e estabilidade; a drenagem vai até 31,05 s e não deve ser misturada com resultados de medição.

## Avaliação editorial do manuscrito

A comparação de quatro tratamentos forma uma história coerente para ICIT se for apresentada como avaliação aplicada, limitada ao benchmark fixo de rede veicular zonal. O título atual é adequado. A formulação da introdução “no controlled comparison exists” precisa ser qualificada e delimitada: Migge/Navet e Maile já comparam mecanismos em contextos relacionados. Restrinja a lacuna à combinação específica de topologia ZB-3T, catálogo, fatores de carga, alinhamentos e métricas de imagem/fluxos usada aqui. A frase de escopo de que apenas o tratamento muda também precisa ser precisa: C1 muda temporização de liberação das câmeras e C3 inclui relógios/gates; são políticas comparadas, não um experimento que isola sempre um mecanismo.

| Afirmação | Recomendação | Motivo |
|---|---|---|
| Ausência geral de comparação controlada de mecanismos TSN | Restringir | Migge/Navet e Maile já comparam mecanismos; declarar a lacuna particular do benchmark/alinhamento. |
| Alinhamento degrada entrega em SP e pre-shaping a recupera | Manter com escopo e ressalva | Forte em C0 L3 A0/A1 e C1 L3/A1; diferença de software C0/C1 e apenas um benchmark. |
| CBS calibrado amplia fronteira sobre nominal | Remover | Não há CBS nominal no artigo; C2 passa 59/180 e falha nas 120 execuções L0/L1. |
| TAS melhora timing dos freios | Reformular | C3−C2 não isola TAS; em L0/A0 a cauda aumenta ~58 µs, embora os deadlines passem. |
| Nenhum tratamento domina | Restringir | Trade-offs observados são compatíveis, mas C3 parcial e sem BE/alta carga completa. |
| Conformidade de sincronização | Precisar | Apenas amostras abaixo de 1 µs; contínua não verificada. |

A frase “no controlled comparison exists” deve ser delimitada à combinação concreta de benchmark, alinhamento, carga e completude de imagem e qualificada como lacuna identificada pelos autores; a busca feita aqui não é uma revisão sistemática que prove inexistência. O artigo tem material empírico coerente para esse escopo, mas não deve vender contribuição como novo protocolo ou prova geral de superioridade. O eixo recomendado é entrega de aplicações sob alinhamento e shaping, com CBS entre cargas como contraste de limite/transferência; C3 combinado fica como resultado parcial. C2 nominal não é parte da análise, e não se pode afirmar calibração superior ao nominal.

## Base recomendada para Results, Conclusions e Abstract

### Results (ordem sugerida)

1. **Sensibilidade de SP a A0/A1:** 30/30 versus 0/30 em C0 L3; quantificar 579.892 perdas e perdas/incompletude F02/F05; ressalvar domínio benchmark.
2. **Pre-shaping:** C1 remove essas perdas/incompletudes na L3/A1, mas acrescenta 8,978 ms (F02) e 14,134 ms (F04) ao p99 de conclusão em L0/A0; mostrar todos os denominadores e deadline.
3. **Transferência CBS por carga:** C2 0/120 em L0/L1 e 59/60 L2; separar TC4 overflow e F06/F07 p99 >100 µs sem perdas. Não comparar com nominal.
4. **CBS/TAS parcial:** C3 90/90 no corte; 60/60 L0 e amostras de L1/L2; brake max 78,461 µs; contrastar p99 pareado +~58 µs com C2 como mudança de política completa.

### Conclusions (até três)

- Neste benchmark e protocolo, o alinhamento de rajadas de câmera torna SP insuficiente em L3/A1, e source pre-shaping restaura completude de imagens ao custo de maior latência de conclusão.
- O CBS calibrado por carga não transfere bem para L0/L1 nesta implementação: coexistem overflow TC4 e deadline misses TC6; os dados apoiam uma fronteira empírica, não causalidade única nem comparação com CBS nominal.
- A configuração CBS/TAS D3 é promissora nas execuções concluídas, mas ainda só tem L0 completamente coberto; não demonstra ganho sobre CBS e aumenta a cauda de freios em L0/A0 mantendo margem observada.

### Abstract (elementos seguros, ainda não redigir)

Problema: convivência de bursts de câmera/sensores e tráfego crítico em convergência zonal; método: comparação OMNeT++/INET de SP, pre-shaping, CBS calibrado e CBS/TAS num catálogo fixo e cargas/alinhamentos; cobertura no corte: 750 execuções incluídas, com C3 combinado parcial (90/180) e L3 excluídos por triagem para dois tratamentos; quantitativos seguros: C0 L3/A1 0/30 versus A0 30/30 e 579.892 perdas; C1 30/30 e imagens completas; C2 CBS 0/120 low-load e 59/60 L2; C3 no corte 90/90 mas apenas L0 completo. Contribuição: evidência experimental delimitada de trade-offs de alinhamento, conclusão de imagem e transferência de reserva, sem garantia analítica nem superioridade universal.

## Literatura e aderência ao ICIT

A literatura já cobre comparação de mecanismos TSN em contexto automotivo (Migge/Navet) e avaliação de mecanismos/efeitos sobre tráfego best effort (Maile et al. 2024, conforme citekey presumido); Luo contribui com arquitetura automotiva simulada; Leal Filho trata sobrecargas transientes ADAS; Ashjaei é referência de estado da arte. A contribuição defensável não é “primeira comparação” ou “CBS/TAS nunca testado”: é o conjunto de resultados por alinhamento, imagem completa e carga para esta topologia/catalogo, mais a observação de que uma política CBS escalada falha em baixa carga enquanto o perfil combinado C3 ainda está parcialmente verificado. O arquivo `.bib`/bibliografia usado pelo manuscrito não estava disponível na árvore lida; `maile2024` corresponde ao trabalho de comparação de mecanismos e best-effort indicado pelo título da seção relacionada, e `ashjaei2021` ao survey automotivo. A identidade exata de `leal2025` deve ser conferida no `.bib` antes de finalizar citações. Leal Filho et al. (ISCC 2025) foi identificado pelo DOI para contexto, mas o citekey não foi validado contra a bibliografia ausente.

A aderência ao ICIT é boa se o framing ligar o estudo a comunicação industrial/veicular e sistemas ciberfísicos de tempo real; a chamada oficial inclui Automotive Control and Transportation Systems, Network-based Control Systems and Applications e a trilha de Industrial Automation, Communication, and Manufacturing. A página oficial indica prazo regular em 27/10/2026 às 23:59 BRT. Não inferir comportamento de hardware real diretamente do simulador nem reivindicar aceitação.

Fontes consultadas para delimitar a contribuição: [Migge/Navet et al. (2018), automotive AVB/TSN](https://orbilu.uni.lu/handle/10993/40623); [Navet et al. (2018), pre-shaping bursty transmissions](https://orbilu.uni.lu/handle/10993/38606); [Luo et al. (2022)](https://www.mdpi.com/1424-8220/22/12/4580); [Maile et al. (2024)](https://doi.org/10.1145/3688268.3688283); [Ashjaei et al. (2021)](https://doi.org/10.1016/j.sysarc.2021.102137); [Leal Filho et al. (ISCC 2025)](https://doi.org/10.1109/ISCC65549.2025.11326440); [ICIT 2027 official site](https://icit2027.ieee-ies.org/). The `.bib` file was not found, so final citekey-to-reference identity should still be checked.

## Pendências materiais

1. Concluir o corte da campanha C3 combinado nas células L1/L2 e as demais posições antes de generalizar para cargas maiores.
2. Reconciliar o ledger/manifests finais do tratamento C2 (histórico C3) e manter os hashes/fontes de todas as execuções.
3. Reduzir o confounding de software na interpretação causal C0−C1; resultados descritivos seguem úteis porque calendários/populações foram pareados.
4. Conferir bibliografia exata e restringir a alegação de lacuna frente à literatura próxima.
5. A sincronização contínua não foi demonstrada; não afeta gates de aplicação atuais, mas limita qualquer afirmação de conformidade de relógio além das amostras.

**Resposta editorial:** os dados sustentam uma contribuição aplicada delimitada para ICIT, desde que a narrativa seja sobre trade-offs medidos em um benchmark veicular zonal e não sobre novidade universal de TSN. C4 não precisa superar C2 para o artigo ser coerente, mas sua campanha incompleta impede uma afirmação geral sobre L1/L2; se os dados finais divergirem, a discussão deve ser atualizada.

### Fontes locais e reprodutibilidade

Os dados derivados e scripts estão no diretório desta análise. Regerar os dados quantitativos e este documento sem iniciar simulação:

```sh
python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/analyze_results.py
python3 simulations/analysis/icit2027_editorial_synthesis_2026-10-27/build_editorial_outputs.py
```

Os resultados C4 são um corte congelado; não execute o script sobre dados parciais sem primeiro decidir se quer um novo corte.
