# Configurações graduais

Somente `base.ini` e `recording.ini` estão ligados a `simulations/omnetpp.ini`.
Os demais `.ini` são contratos comentados, sem seções executáveis: não implementam
os mecanismos, cargas ou agregação. `mechanisms/` substitui o antigo E0–E4.
Ao implementar cada etapa, conectar seus fragmentos explicitamente, conferir a
herança e validar o comportamento antes de anunciar uma configuração C0–C4.
O protocolo final está em `experiments/design.json`; o smoke test usa 1 s sem tráfego.
