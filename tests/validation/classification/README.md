# Validação do C0 — Strict Priority

C0 é o baseline do P1: PCP n é classificado em TCn; cada classe usa FIFO
drop-tail; entre filas elegíveis, vence a TC mais alta (TC7→TC0). Todos os gates
ficam abertos. C0 não usa CBS, TAS com janelas fechadas nem pre-shaping das
câmeras. As liberações do catálogo, incluindo os 30 quadros simultâneos de cada
imagem em A1, permanecem inalteradas.

As filas por classe estão habilitadas nos egressos de switches e de talkers,
incluindo HPC e CPUs zonais. Os limites por fila são 128 KiB nos egressos G1–G4
(uplinks zonais, CSW→HPC, CSW→zonas e caminhos LP/backbone dos transientes),
64 KiB nos talkers CAM1–CAM4 e 32 KiB nos demais egressos. Assim, a fila da
câmera admite os 30 quadros do burst (44.880 B no MAC) sem truncar a carga na
origem. O limite é por classe e em bytes; os drops restantes são localizados
nas filas de rede pela auditoria de saltos.

## Executar a validação P1

Na raiz, com OMNeT++ 6.4.0 carregado e `INET_ROOT` apontando para INET 4.7.0:

```bash
bash scripts/run/build.sh
python3 scripts/run/validate_c0.py --jobs 2
```

O validador executa as oito células `Validate_C0_L0_A0` a `Validate_C0_L3_A1`,
cada uma com seed 41, 1 s de warm-up, 30 s de medição e 50 ms de drenagem. O
verificador do catálogo confere emissões, tamanhos, caminhos, multicast,
conservação em cada salto e descartes. A auditoria do C0 percorre todos os
egressos e suas oito filas: verifica a matriz PCP→TC efetiva, a atividade das
classes esperadas pelos PCPs do catálogo, a ordem descendente SP, gates sempre
abertos, DropTail e a capacidade finita correta.

As amostras de latência por receptor alimentam p99 empírico e máximo observado.
Perdas e entregas atrasadas entram na razão de miss sobre os pacotes oferecidos;
para cada BE são conferidos goodput útil ≥0,95 e perda ≤1%. A ocupação em bits
de cada fila é integrada em seis janelas de 5 s; crescimento sustentado é marcado
quando as médias das três últimas janelas sobem continuamente e aumentam mais
que 5% da capacidade. Histogramas de tempo de fila e utilização também são
exigidos. F21/F22 precisam manter as mesmas escolhas transientes entre L/A.
Resultados detalhados por célula ficam em `simulations/results/C0/p1-validation-64KiB/`
e o consolidado em `C0_acceptance.json`.

O comando termina quando a evidência técnica está completa. Cada célula é
classificada separadamente como viável ou não viável pelos critérios do P1; uma
célula não viável continua sendo um resultado válido do baseline C0. A matriz
seed 41 com 64 KiB nas câmeras foi executada: 1/8 células atende à viabilidade,
embora todas tenham zero drops, zero overflow nas filas CAM e filas estáveis.
Os resultados antigos de 32 KiB foram preservados em `p1-validation/` e são supersedidos para a
configuração corrigida. A análise de aceitação usa F01 e F06/F07 como
hard-critical conforme os rótulos `high-hard` do catálogo. O diagnóstico
detalhado da rodada corrigida está no relatório comparativo C0/C1. Os resultados
antigos estão documentados em
[`c0-p1-results.md`](c0-p1-results.md); relatórios completos por fluxo permanecem
na pasta de resultados ignorada pelo Git.

Para reclassificar os resultados já coletados de acordo com o catálogo atualizado,
sem executar de novo as simulações:

```bash
python3 scripts/run/validate_c0.py --reassess-existing
```

Para inspecionar uma célula completa pela IDE:

```bash
bash simulations/run -u Qtenv -c Validate_C0_L2_A1
```

As configurações `C0_Lx_Ay` executam a duração de campanha do P1 (1 s de warm-up,
30 s de medição e 50 ms para drenagem) e gravam resultados em
`simulations/results/C0/`. Ainda não são as 30 repetições finais: calibração e
piloto usam seeds próprias, separadas de 1001–1030.

## O que conferir

- Os pacotes atingem a fila TC indicada pelo PCP em talkers e switches.
- Fila selecionada segue a ordem decrescente de TC e os gates permanecem abertos.
- Capacidade efetiva por classe é 128 KiB em G1–G4, 64 KiB nos talkers CAM1–CAM4
  e 32 KiB nos demais egressos.
- `queues.csv` e `drops.csv` conservam os pacotes em cada salto; não há flooding
  nem caminhos fora do catálogo.
- `C0_acceptance.json` reporta p99/máximo, misses, goodput, perdas, ocupação por
  classe e a classificação de estabilidade para cada carga/agregação.

C0 constitui a referência para C1–C4. Esta validação usa a duração P1 em uma
seed de auditoria; as 30 seeds 1001–1030 continuam reservadas à campanha final.
C1 aplica pre-shaping somente a F02–F05 e repete a matriz com as categorias de
criticalidade canônicas. Consulte `../source_preshaping/README.md`.
