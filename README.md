# Zonal IVN TSN

Estrutura para implementar gradualmente o P1 atualizado: benchmark Ethernet de
três zonas, 22 fluxos e comparação de Strict Priority, pre-shaping, CBS e TAS.

## Estado atual

Os oito microcenários INET em `simulations/tsn_validation/` estão preservados,
com suas configurações e documentação de validação. A topologia P1 está implementada:
29 nós Ethernet, 28 enlaces full-duplex e três controladores com switch e CPU.
`TopologyValidation` permite inspecioná-la sem tráfego; `TopologyConnectivity`
verifica conectividade com sondas ICMP isoladas do catálogo. `SmokeTest` é um alias
para `TopologyValidation`. A disposição visual usa o fundo `background/car` do INET em 1280×720:
frente à direita, Z1 na dianteira esquerda (acima), Z2 na dianteira direita
(abaixo) e Z3 na traseira. Câmeras, LiDAR e radares usam ícones distintos; abrir
Z1/Z2/Z3 revela o switch e a CPU. As cores dos enlaces indicam suas classes;
a legenda informa as velocidades e os tooltips dos acessos mantêm seus detalhes.

Os fluxos F01–F22 e os tratamentos C0–C4 continuam pendentes; o CSV contém apenas
o cabeçalho. Não há executor de campanha nem scripts de análise implementados.
A validação da topologia não equivale à validação do benchmark completo.

## Estrutura

```text
src/                           Componentes reutilizáveis
  applications/                Geração de tráfego, caso exija extensões
  common/                      Canal Ethernet do P1 (ZonalEthernetLink)
  nodes/                       ZonalController implementado (switch + CPU)
  queueing/                    Extensões de filas, somente se necessárias
simulations/
  omnetpp.ini                  TopologyValidation / TopologyConnectivity
  run                          Launcher legado do executável local
  tsn_validation/              MC01–MC08 preservados
  zonal/
    networks/                  ZonalIVN.ned (topologia completa)
    configs/                   Base, recording e contratos de configuração
      mechanisms/              Contratos C0–C4, ainda não executáveis
    traffic/                   Esquema do catálogo e futuras entradas
images/                        Fundo do veículo e ícone de câmera do INET
experiments/                   design.json: fatores e protocolo planejado
tests/validation/              Validação incremental do benchmark
  topology/                    Sondas ICMP, verificador e guia Qtenv
  traffic/                     Catálogo, taxas, fases e eventos
  classification/              VLAN/PCP→TC, SP e buffers
  source_preshaping/            C1
  cbs/                         C2/C3 e reservas
  tas/                         C4 e sincronização
  integration/                 Piloto integrado
scripts/run/                   Futuro executor e triagem
scripts/analysis/              Futura extração e análise
docs/
  design/                      Plano incremental baseado no P1
  decisions/                   Decisões de estrutura e compatibilidade
  traffic-catalog/             Contrato e proveniência dos fluxos
  figures/                     Figuras selecionadas
  report/                      Fontes futuras do relatório
```

`results/raw/`, `results/processed/` e `results/manifests/` serão criados pelas
execuções futuras e são ignorados pelo Git. Os microcenários mantêm seus caminhos
de saída existentes, conforme seus próprios INIs.

## Experimento planejado

| Configuração | Tratamento |
|---|---|
| C0 | Strict Priority |
| C1 | C0 + pre-shaping nas câmeras F02–F05 |
| C2 | CBS nominal em TC6 e TC4 |
| C3 | CBS calibrado em L2/A1, razões congeladas e teto de 75% por porta |
| C4 | CBS de C3 + TAS em sete egressos e gPTP |

L0/L1/L2/L3 usam fatores 0,5/1/2,5/4 somente nos fluxos escaláveis.
A0 distribui as rajadas; A1 as alinha. A matriz tem 40 células lógicas;
C3/C4 em L3, para A0 e A1, são inviáveis por reserva. Restam até 36 células
candidatas e 1.080 execuções, sujeitas à triagem adicional de gates em C4.
Cada execução final terá 1 s de warm-up e 30 s de medição, com seeds 1001–1030
pareadas. Calibração e piloto usam seeds separadas, ainda a definir.

ATS, PSFP, preempção e síntese automática de GCL ficam fora do benchmark P1,
mas seus microcenários continuam disponíveis como referência INET.

## Ambiente e execução

Topologia executada e verificada em OMNeT++ 6.4.0 e INET 4.7.0.
A IDE referencia `inet-4.7.0`; importar e compilar essa dependência antes do
projeto. As raízes NED são `simulations`, `src` e `tests`, conforme `.nedfolders`.
O P1 cita INET 4.6 em CBS+TAS; a compatibilidade de crédito/gates deve ser
verificada antes de implementar C4 (ver a decisão 0001).

Na IDE OMNeT++, importar este projeto, conferir a referência INET e compilar.
Abrir `simulations/omnetpp.ini`, executar com Qtenv e selecionar
`TopologyValidation`. A rede não gera tráfego de aplicação nessa configuração;
é normal terminar sem animação de pacotes. Selecionar `TopologyConnectivity`
para observar sondas ICMP entre os nós.

O [guia de validação da topologia](tests/validation/topology/README.md) traz
mapa de portas, critérios de inspeção e comandos Cmdenv. Os testes verificaram
as 56 interfaces, os 28 enlaces com 100 ns, os caminhos L2 estáticos e 54/54
respostas ICMP sem perdas.
Para os microcenários, abrir o respectivo `mcXX.ini` e selecionar sua configuração;
consultar [a documentação preservada](simulations/tsn_validation/README.md).
O comando `make` da raiz delega ao Makefile gerado em `src`; requer o ambiente
OMNeT++ configurado. `simulations/run` é um launcher legado, não uma campanha P1.

## Próximas etapas e rastreabilidade

Seguir [o plano incremental](docs/design/p1-implementation.md), os critérios em
[tests/validation](tests/validation/README.md) e o
[plano experimental](experiments/README.md). A organização e a diferença de
versões estão registradas em [0001](docs/decisions/0001-p1-structure.md).
Registrar versões, revisão, C/L/A/seed, durações, parâmetros resolvidos e status
de admissibilidade por execução; separar dados brutos, processados e metadados.
