# Configurações executáveis e contratos

A entrada é `simulations/omnetpp.ini`.

| Arquivo | Responsabilidade |
|---|---|
| base.ini / topology.ini / recording.ini | Validação isolada da topologia |
| catalog-bindings.ini | Gerado: aplicações, streams, VLAN/PCP e tabelas MAC |
| loads.ini | Seleção L0–L3 |
| aggregation.ini | Seleção A0/A1 |
| classification.ini | PCP=TC, SP e buffers por classe nos switches |
| traffic.ini | Duração, RNG, registros e modos de validação |
| mechanisms/ | Contratos C0–C4 ainda não ligados às execuções |
| synchronization.ini | Contrato gPTP para a etapa C4 |

`TopologyValidation` é a rede sem aplicações; `TopologyConnectivity` usa ICMP;
`SmokeTest` continua como alias. `Traffic_Lx_Ay` ativa os 22 fluxos, 1 s de warm-up,
30 s de medição e 50 ms de drenagem. `Validate_Lx_Ay` usa 40 ms de warm-up e
2 s medidos; `ValidateReseed` verifica seed diferente. `ValidateSignatures`
percorre deterministicamente todas as assinaturas, somente com F21/F22.

Não chamar TrafficCatalog de C0 final: os switches já usam SP e buffers P1,
mas as origens mantêm staging FIFO sem limite nesta etapa. A política das
origens e os mecanismos de shaping permanecem separados da geração de tráfego.
`catalog-bindings.ini` substitui o configurador MAC automático por entradas
estáticas com VLAN; o configurador automático permanece na topologia sem tráfego.

Depois de editar o CSV, executar `python3 scripts/catalog/generate.py` na raiz.
