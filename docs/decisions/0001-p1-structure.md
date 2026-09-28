# 0001 — Separar exploração INET do benchmark P1

- Preservar integralmente `simulations/tsn_validation/`, inclusive MC05–MC08,
  embora seus mecanismos não façam parte do experimento atualizado.
- Manter as raízes NED `src`, `simulations`, `tests` e metadados da IDE.
- Mover a rede vazia para `simulations/zonal/networks/` e atualizar seu pacote
  e referência. Substituir E0–E4 por contratos C0–C4 ainda não executáveis.
- Separar componentes reutilizáveis, rede, fragmentos de configuração, entradas,
  desenho experimental, testes incrementais, execução e análise.
- Não apresentar smoke test vazio como validação de tráfego ou mecanismos.
- O ambiente documentado é OMNeT++ 6.4.0 / INET 4.7.0; `.project` referencia
  `inet-4.7.0`. P1 cita INET 4.6 para CBS+TAS. Antes de C4, verificar no ambiente
  efetivo a evolução de crédito com gates fechados e registrar a versão/commit.
  Esta reorganização não troca dependências nem confirma equivalência entre versões.
