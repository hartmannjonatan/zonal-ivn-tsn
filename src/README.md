# Módulos reutilizáveis

- `common/ZonalEthernetLink.ned`: canal físico P1, 100 ns, sem erros; padrão
  1 Gbit/s, substituído por 100 Mbit/s nos acessos LA-L.
- `nodes/ZonalController.ned`: composto implementado com ZSW (TsnSwitch),
  ZCPU (TsnDevice), LP interno e portas transparentes de backbone/acesso.
  O módulo composto não representa outro nó de encaminhamento.
- `applications/CatalogUdpApp`: C++/NED de emissão e recepção por fluxo;
  periodicidade, rajadas, segmentação, latência e deadlines.
- `common/TrafficPlan`: carrega o catálogo e pré-sorteia eventos com RNGs dedicados.
- `common/TrafficAudit`: observador passivo dos quadros PHY e das filas TC;
  verifica VLAN/PCP, MTU, overhead, IFG e produz evidências por egresso.
- `queueing/`: reservado a extensões de filas, somente se necessárias.

A rede completa pertence a `simulations/zonal/networks/`. A topologia isolada usa apenas
NED/INET; as configurações de tráfego exigem compilar os novos módulos C++.
