# Configurações graduais

`base.ini`, `topology.ini` e `recording.ini` estão ligados a
`simulations/omnetpp.ini`, que também inclui as sondas diagnósticas em
`tests/validation/topology/connectivity.ini`.

- `TopologyValidation`: topologia P1 completa, 1 s, sem aplicações.
- `TopologyConnectivity`: mesma rede, com sondas ICMP de validação.
- `SmokeTest`: alias de `TopologyValidation`.

`topology.ini` fixa os bitrates das interfaces conforme os canais NED, instala
endereçamento/encaminhamento estático e desativa aprendizado MAC, STP,
cut-through, sincronização e shaping nesta etapa. Os índices das portas estão
em `tests/validation/topology/README.md`; preservá-los ao acrescentar os fluxos.

Os demais `.ini` são contratos comentados sem seções executáveis: mecanismos,
classificação, cargas e agregação ainda não estão implementados. Ao concluir
cada etapa, conectar seus fragmentos e verificar o comportamento antes de
anunciar uma configuração C0–C4. O protocolo final fica em
`experiments/design.json`; as validações de topologia não são execuções finais.
