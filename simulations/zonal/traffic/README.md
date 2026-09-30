# Catálogo executável F01–F22

`flows.csv` é a fonte canônica dos endpoints, tamanhos por camada, emissão,
offsets/fases, deadline, criticidade, VLAN, PCP e escalabilidade. Os tamanhos de
F21/F22 representam o segmento máximo; a última mensagem pode ser menor.
`transients.csv` contém os dez pares medidos duração–volume (MB decimal).

Depois de alterar os CSVs, executar na raiz:

```bash
python3 scripts/catalog/generate.py
python3 scripts/catalog/generate.py --check
```

O gerador verifica tamanhos e taxas e produz `catalog.xml` e
`../configs/catalog-bindings.ini`. Não editar esses dois arquivos gerados.
O XML alimenta `TrafficPlan`; o INI associa as 45 aplicações (22 emissores e
23 receptores), identifica streams por porta UDP 5000+ID, codifica VLAN/PCP e
instala tabelas de encaminhamento por VLAN nos quatro switches.

F14 usa uma única transmissão UDP para 239.0.0.14, MAC 01-00-5E-00-00-0E,
VLAN 10. O CSW replica para eth1/eth2; Z1/Z2 encaminham para seus displays em
eth7. Não há replicação na aplicação nem transmissão de F14 para Z3.

Ver `docs/traffic-catalog/README.md` para as regras completas e
`tests/validation/traffic/README.md` para simular e conferir as evidências.
