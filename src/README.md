# Módulos reutilizáveis

- `common/ZonalEthernetLink.ned`: canal físico P1, 100 ns, sem erros; padrão
  1 Gbit/s, substituído por 100 Mbit/s nos acessos LA-L.
- `nodes/ZonalController.ned`: composto implementado com ZSW (TsnSwitch),
  ZCPU (TsnDevice), LP interno e portas transparentes de backbone/acesso.
  O módulo composto não representa outro nó de encaminhamento.
- `applications/`: reservado a extensões de rajadas/pre-shaping e eventos,
  se os componentes INET não forem suficientes.
- `queueing/`: reservado a extensões de filas, somente se necessárias.

A rede completa pertence a `simulations/zonal/networks/`. A topologia usa apenas
NED e componentes INET existentes; não exige novo código C++.
