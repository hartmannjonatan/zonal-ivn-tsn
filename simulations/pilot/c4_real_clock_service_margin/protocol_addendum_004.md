# Technical addendum 004 — queue dequeue signal

The installed INET 4.7 `PacketQueue::pullPacket()` emits `packetPulled`, not `packetPulledOut`. The first packet trace therefore recorded queue admission and PHY transmission but no queue-dequeue identity. The B run's application validator passed, but it cannot support the required per-packet queue-service chronology; it is retained as technically incomplete under `results/technical/attempt_002_missing_queue_pull/`.

The isolated probe now subscribes to `packetPulled` on each `PacketQueue` and labels it `queue_pulled_out`. Before spending the second and final technical replacement, a 1.02 s traffic smoke must demonstrate nonzero packet-identified push, pull, and transmission events with matching flow/sequence identities. If that smoke passes, repeat B once with the same seed, calendar, and settings. The smoke is technical only and does not count as a methodological execution.
