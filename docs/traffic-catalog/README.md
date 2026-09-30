# Catálogo F01–F22 — implementado

A fonte canônica está em `simulations/zonal/traffic/flows.csv`, transcrita das
tabelas 1, 2a e 2b do P1. A tabela 3 está em `transients.csv` no mesmo diretório.
A topologia e os nomes de portas são os da etapa anterior.

| Fluxos | Origem → destino | Emissão nominal | Payload / wire por pacote | PCP |
|---|---|---|---|---:|
| F01 | LiDAR1 → HPC | 100 µs, offset 0 | 1472 / 1542 B | 6 |
| F02–F03 | CAM1–CAM2 → HPC | 30 mensagens por 16 ms | 1446 / 1516 B | 6 |
| F04–F05 | CAM3–CAM4 → HPC | 30 mensagens por 16 ms | 1446 / 1516 B | 4 |
| F06–F07 | RADAR1–RADAR2 → HPC | 1 ms, offsets 20/25 µs | 14 / 84 B | 6 |
| F08–F10 | HPC → BRAKE1–BRAKE3 | 100 µs, offsets 0/2/4 µs | 14 / 84 B | 7 |
| F11–F13 | HPC → AUDIO1–AUDIO3 | 200 µs, offsets 0/5/10 µs | 206 / 276 B | 6 |
| F14 | HPC → DISPLAY1 e DISPLAY2 | multicast a cada 200 µs | 1472 / 1542 B | 4 |
| F15–F17 | HPC → WINDOW1–WINDOW3 | 200 µs, offsets 50/55/60 µs | 14 / 84 B | 3 |
| F18–F20 | HPC → BE1–BE3 | 616,8 µs, fases 0/T/3/2T/3 | 1472 / 1542 B | 0 |
| F21–F22 | Z1_CPU/Z2_CPU → Z3_CPU | eventos empíricos | até 1472 / 1542 B | 6 |

Os VLANs individuais, deadlines e identificadores de proveniência constam no
CSV. As portas UDP 5001–5022 identificam os fluxos; não são portas físicas.

## Camadas e ocupação wire

Para os fluxos permanentes, IP = payload + 28 B (IPv4 20 + UDP 8),
MAC = max(64 B, IP + 22 B), wire = MAC + 20 B (preâmbulo/SFD 8 + IFG 12).
O IFG não é anexado ao pacote: o INET reserva o tempo de 96 bits entre quadros.
A auditoria verifica cabeçalhos VLAN/PCP, comprimentos e espaçamento físico de
cada quadro transmitido. A aplicação usa metadados de criação/sequência que
não acrescentam bytes ao payload configurado.

A taxa nominal é N × wire × 8 / período. Ela é diferente do goodput da aplicação.
Para F14, LC recebe uma cópia; o CSW produz as duas ramificações multicast.
As tabelas MAC incluem a VLAN: entradas automáticas apenas para VLAN 0 causariam
flooding quando aplicadas a este catálogo marcado.

## L0–L3 e A0/A1

- L0/L1/L2/L3: k = 0,5/1/2,5/4, com T' = T/k apenas para
  F01–F07, F11–F13 e F18–F20. Tamanho, prioridade, VLAN e deadline não mudam.
- F08–F10, F14–F17 são fixos; F21/F22 não são multiplicados por k.
- Câmeras: 30 mensagens liberadas juntas por imagem. A0 usa fases
  0/C/4/C/2/3C/4; A1 usa fase zero para todas. C é o ciclo já escalado.
- BE: fases 0/T'/3/2T'/3 em ambas as agregações.
- Os offsets absolutos em µs dos demais fluxos permanecem fixos.

Não há pre-shaping de câmera nesta etapa. As filas FIFO de origem do INET
armazenam a imagem liberada, serializada pelo enlace a 1 Gbit/s. Os switches
usam PCP n → TCn explícito, SP, drop-tail por classe e capacidades 128 KiB nas
saídas de backbone/LP e 32 KiB nos demais acessos. Os talkers ainda conservam
FIFO sem limite de capacidade: isso é uma condição do suporte de validação do
catálogo, não representa a configuração C0. Em C0, os talkers também têm filas
por PCP e capacidades drop-tail finitas conforme
`tests/validation/classification/README.md`; as liberações de câmera continuam
em rajada e não são pré-escalonadas. Assim, a verificação do catálogo permanece
separada da comparação de tratamentos.

## Transientes e correção de interpretação

F21 e F22 sorteiam, independentemente e com reposição uniforme, um dos dez pares
LF1–LF5/FR1–FR5 por segundo medido. Ambos usam o conjunto completo; LF/FR
identificam a origem empírica, não restringem a zona do benchmark.
F21 começa em warm-up + bloco + 5 ms. Em A0, F22 começa 10 ms após o término
de F21; em A1, os dois começam juntos. Cada fluxo usa RNG dedicado; a mesma seed
preserva as assinaturas quando L ou A muda. A seed também está registrada nos
resultados OMNeT++ e nos parâmetros da configuração.

**Decisão confirmada pelo usuário:** preservar o volume empírico como bytes da
aplicação. Segmentar em payloads de até 1472 B para manter IPv4 ≤1500 B,
conservando exatamente o volume com um último segmento parcial. O início de
cada segmento j é início_evento + duração × j/N, para j=0..N−1.

Isso corrige a aproximação wire do P1: para segmentos completos, o fator é
1542/1472 sobre o volume de aplicação, e não 1542/1500. A duração e o volume
medidos são mantidos. A auditoria soma os tamanhos reais, inclusive segmento
final e eventual padding Ethernet. Logo, as taxas wire de F21/F22 diferem das
aproximações impressas no P1; essa diferença é intencional e autorizada.

## Deadlines e limites das métricas

Deadlines estão disponíveis no CSV/XML e nas saídas TX/RX: 100 µs para
F01/F06–F10; 10 ms para F02/F03/F11–F13/F21/F22; 30 ms para F04/F05/F14;
50 ms para F15–F17. BE não tem deadline temporal. A anotação “100 µs / 5 hops”
do P1 foi conservada como deadline de 100 µs, sem multiplicá-la por cinco.

A recepção calcula latência desde a geração, máximo e contagem de violações.
Os contadores `measured_*` usam a coorte gerada durante a janela de medição;
a simulação permite mais 50 ms para drenagem. São diagnósticos de conservação,
não estimadores finais de throughput por instante de recepção para P3/P4.
Aprovar o catálogo não implica cumprir todos os deadlines sob carga, nem
aprovar CBS/TAS ou concluir a campanha experimental.
