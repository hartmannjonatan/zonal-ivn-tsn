# Piloto isolado de reclassificação PCP/TC

Este arquivo e os INIs, catálogos, reservas, históricos e resultados abaixo pertencem somente ao piloto. O P1 e as configurações oficiais não foram alterados por esta geração.

| Fluxo | VLAN | Original PCP→TC | Mecanismo original | Variante PCP→TC | Mecanismo na variante |
|---|---:|---:|---|---:|---|
| F01 LiDAR1→HPC | 1 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 6→6 | C0=SP; C1=SP; C2=TC6 CBS |
| F02 CAM1→HPC | 2 | 6→6 | C0=SP; C1=SP+camera pre-shaping; C2=TC6 CBS | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS |
| F03 CAM2→HPC | 7 | 6→6 | C0=SP; C1=SP+camera pre-shaping; C2=TC6 CBS | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS |
| F04 CAM3→HPC | 13 | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS |
| F05 CAM4→HPC | 14 | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS | 4→4 | C0=SP; C1=SP+camera pre-shaping; C2=TC4 CBS |
| F06 RADAR1→HPC | 6 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 6→6 | C0=SP; C1=SP; C2=TC6 CBS |
| F07 RADAR2→HPC | 12 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 6→6 | C0=SP; C1=SP; C2=TC6 CBS |
| F08 HPC→BRAKE1 | 3 | 7→7 | C0=SP; C1=SP; C2=SP | 7→7 | C0=SP; C1=SP; C2=SP |
| F09 HPC→BRAKE2 | 8 | 7→7 | C0=SP; C1=SP; C2=SP | 7→7 | C0=SP; C1=SP; C2=SP |
| F10 HPC→BRAKE3 | 15 | 7→7 | C0=SP; C1=SP; C2=SP | 7→7 | C0=SP; C1=SP; C2=SP |
| F11 HPC→AUDIO1 | 4 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |
| F12 HPC→AUDIO2 | 9 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |
| F13 HPC→AUDIO3 | 16 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |
| F14 HPC→DISPLAY1;DISPLAY2 | 10 | 4→4 | C0=SP; C1=SP; C2=TC4 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |
| F15 HPC→WINDOW1 | 5 | 3→3 | C0=SP; C1=SP; C2=SP | 3→3 | C0=SP; C1=SP; C2=SP |
| F16 HPC→WINDOW2 | 11 | 3→3 | C0=SP; C1=SP; C2=SP | 3→3 | C0=SP; C1=SP; C2=SP |
| F17 HPC→WINDOW3 | 17 | 3→3 | C0=SP; C1=SP; C2=SP | 3→3 | C0=SP; C1=SP; C2=SP |
| F18 HPC→BE1 | 18 | 0→0 | C0=SP; C1=SP; C2=SP | 0→0 | C0=SP; C1=SP; C2=SP |
| F19 HPC→BE2 | 19 | 0→0 | C0=SP; C1=SP; C2=SP | 0→0 | C0=SP; C1=SP; C2=SP |
| F20 HPC→BE3 | 20 | 0→0 | C0=SP; C1=SP; C2=SP | 0→0 | C0=SP; C1=SP; C2=SP |
| F21 Z1.ZCPU→Z3.ZCPU | 21 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |
| F22 Z2.ZCPU→Z3.ZCPU | 22 | 6→6 | C0=SP; C1=SP; C2=TC6 CBS | 4→4 | C0=SP; C1=SP; C2=TC4 CBS |

## Divergências resolvidas

O catálogo confirmou que F02/F03 e F11–F13 eram PCP6/TC6, enquanto a proposta os coloca em TC4; F21/F22 também eram PCP6/TC6 e passam a TC4. F04/F05 e F14 já eram PCP4/TC4. F01/F06/F07 já eram PCP6/TC6. A variante troca PCP para 4 nos sete fluxos divergentes; a classificação permanece identidade PCPn→TCn. VLAN, encaminhamento, destino, tamanho e calendário não mudam.

A tabela deve ser lida por tratamento: C0 usa SP; C1 usa SP e aplica pre-shaping somente às câmeras; C2 usa CBS nominal em TC4/TC6 com SP nas demais TCs. O algoritmo, a ordem dos alvos, os limites e o calendário estão em `search_protocol.json`.

## Reservas nominais L2

Os CSVs `configs/cbs_original_nominal.csv` e `configs/cbs_variant_nominal.csv` contêm cada porta/TC, fluxos permanentes roteados, `R_wire`, soma por porta e margem ao teto de 75%. Transientes F21/F22 não entram nas somas.
