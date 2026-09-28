# Módulos reutilizáveis

- `common/`: identificadores de fluxos, unidades e instrumentação compartilhada.
- `applications/`: extensões de geração de rajadas/pre-shaping e eventos, se necessárias.
- `queueing/`: extensões somente quando os módulos INET não forem suficientes.
- `nodes/`: futuro `ZonalController`, composto por TsnSwitch + TsnDevice via LP.

Nenhum desses módulos específicos está implementado. Preferir componentes INET.
A rede completa pertence a `simulations/zonal/networks/`.
