# Implementação gradual do P1 atualizado

Referência de projeto: P1.pdf fornecido pelo usuário, seções 2–6. O documento
fixa o benchmark, mas não prescreve a organização interna de diretórios (6.1).
Topologia e catálogo de tráfego estão implementados e validados em Cmdenv.
VLAN/PCP e encaminhamento multicast estão ativos. Os tratamentos completos
C0–C4 e a campanha experimental ainda não estão concluídos.

## Etapas e entregas

1. **Topologia — concluída:** `simulations/zonal/networks/ZonalIVN.ned`,
   `src/nodes/ZonalController.ned` e `src/common/ZonalEthernetLink.ned`
   implementam todos os nós/enlaces do P1. HPC e CPUs usam TsnDevice; CSW e
   switches zonais usam TsnSwitch. Cada controlador agrupa switch e CPU ligados
   por LP; a CPU não é intermediária do tráfego de outros nós. Endereçamento e
   tabelas L2 são instalados na inicialização, com aprendizado MAC desativado.
   `TopologyValidation` e `TopologyConnectivity` estão executáveis; a conferência
   dos resultados confirma 29 nós, 28 enlaces, velocidades, propagação e 54/54
   respostas ICMP. Ver `tests/validation/topology/README.md` para inspeção Qtenv.
2. **Tráfego — concluído:** F01–F22 estão no CSV canônico e associados às
   aplicações pelo gerador de XML/INI. Há tabelas MAC por VLAN, multicast F14
   com replicação no CSW, eventos F21/F22, seleção L0–L3/A0–A1 e auditoria dos
   quadros reais. A matriz e as dez assinaturas foram verificadas. Ver
   `tests/validation/traffic/README.md`. A interpretação dos volumes transientes
   como payload foi confirmada pelo usuário e corrige o fator wire do P1.
3. **C0:** VLAN/PCP, PCP=TC, SP e buffers finitos já suportam a validação nos
   switches. Falta fechar a política de filas nas origens e a configuração C0
   completa; o catálogo usa FIFO de origem sem limite para staging das imagens.
4. **C1:** pre-shaping só de F02–F05; espaçamento ADAS min(324 µs,C/30),
   vision min(500 µs,C/30). Preservar ciclo, volume e deadlines.
5. **C2/C3:** CBS TC6/TC4, reservas nominais por porta excluindo transientes;
   calibrar C3 em L2/A1, congelar razões e aplicar limite de 75% por porta.
6. **C4:** CBS congelado + TAS nos sete egressos HPC→CSW,
   CSW→ZSW_i e ZSW_i→BRAKE_i. Ciclo de 100 µs: TC7 por 10 µs,
   TC0–TC6 por 77 µs, todos fechados por 13 µs. Sem preempção.
   HPC é grandmaster; CSW e switches zonais são bridges. Sync de 125 ms,
   peer delay de 1 s; controle gPTP em TC7. BRAKE_i não executa TAS.
7. **Piloto e campanha:** validar métricas, sincronização e estabilidade;
   congelar parâmetros e análise antes das seeds finais. Usar a matriz de
   `experiments/design.json`, incluindo as fronteiras de inviabilidade.

## Topologia fixa

- Z1: Z1_SW, Z1_CPU, LiDAR1, CAM1, BRAKE1, WINDOW1, AUDIO1, DISPLAY1, BE1.
- Z2: Z2_SW, Z2_CPU, RADAR1, CAM2, BRAKE2, WINDOW2, AUDIO2, DISPLAY2, BE2.
- Z3: Z3_SW, Z3_CPU, RADAR2, CAM3, CAM4, BRAKE3, WINDOW3, AUDIO3, BE3.
- LC (HPC–CSW), LB (CSW–zonas), LP (switch–CPU) e LA-H (LiDAR/câmeras):
  1 Gbit/s. LA-L (demais endpoints): 100 Mbit/s. Todos full-duplex, 100 ns.
- A árvore já oferece o caminho de F14: LC uma vez e ramificação no CSW para
  DISPLAY1 e DISPLAY2. A inscrição multicast, VLAN e aplicação de F14 pertencem
  à etapa de tráfego e estão configuradas no catálogo gerado.
- Encaminhamento estático e store-and-forward; sem STP, falhas ou redundância.

## Apresentação visual

`ZonalIVN` usa `bgi=background/car;bgb=1280,720`, como o showcase in-vehicle
INET. A frente do veículo fica à direita: Z1 ocupa a dianteira esquerda (acima),
Z2 a dianteira direita (abaixo) e Z3 a traseira. Os dispositivos são posicionados
nas regiões de montagem correspondentes, com ícones específicos para câmeras e
metáforas visuais de scanner/antena para LiDAR/radar. As coordenadas são apenas
ilustrativas; não alteram os enlaces ou seus parâmetros físicos.

## Aceitação

A validação incremental fica em `tests/validation/`. Os MC01–MC08 são evidência
isolada de mecanismos INET, não comprovação do benchmark completo.
C4 precisa verificar o orçamento aberto de 77%, o serviço efetivo de TC6/TC4,
filas estáveis, taxas entregues e sincronização durante o warm-up de 1 s.
A viabilidade exige ausência de misses hard-critical, até 1% em soft-deadline,
goodput recebido/ofertado de pelo menos 0,95 e perda de até 1% para cada BE,
e ausência de crescimento contínuo de filas após warm-up.

ATS, PSFP, preempção, síntese automática de GCL, FRER e falhas estão fora do
benchmark. Seus microcenários permanecem preservados para consulta.
