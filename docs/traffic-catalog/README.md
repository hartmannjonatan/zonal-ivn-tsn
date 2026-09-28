# Contrato do catálogo F01–F22

Transcrever e conferir as tabelas 1, 2a, 2b e 3 do P1 antes de gerar tráfego.
O cabeçalho em `simulations/zonal/traffic/flows.csv` é apenas um esquema vazio,
não um catálogo implementado. Tamanhos e períodos devem trazer unidade explícita;
campos não aplicáveis ficam vazios, nunca preenchidos com valores inventados.

- F01: LiDAR1→HPC; F02–F05: CAM1–CAM4→HPC; F06–F07: RADAR1–RADAR2→HPC.
- F08–F10: HPC→BRAKE1–BRAKE3; F11–F13: HPC→AUDIO1–AUDIO3.
- F14: HPC→DISPLAY1 e DISPLAY2 (um fluxo multicast).
- F15–F17: HPC→WINDOW1–WINDOW3; F18–F20: HPC→BE1–BE3.
- F21/F22: Z1_CPU/Z2_CPU→Z3_CPU, pares empíricos duração–volume da tabela 3.

Escalar apenas F01–F07, F11–F13 e F18–F20 por T'=T/k.
F08–F10, F14–F17 são fixos; F21–F22 são eventos sem multiplicação por k.
Câmeras: 30 payloads de 1.446 B por ciclo nominal de 16 ms. Em A0, fases
0,C/4,C/2,3C/4; em A1, todas zero. C1 altera apenas espaçamento intrarajadas.
F21 começa 5 ms após cada segundo medido; em A0 F22 começa 10 ms após o
fim de F21, em A1 ambos começam juntos. Reutilizar a sequência amostrada por seed.

Distinguir payload, IP, MAC e wire: para dados de Luo, app=IP−28 B,
MAC=IP+22 B, wire=MAC+20 B. Taxas de enlace incluem preâmbulo e IFG.
Conservar proveniência reportada/derivada/assumida e a fórmula de conversão.
