# 0002 — Catálogo de tráfego, multicast e evidências

- CSV é a fonte canônica; XML e vínculos INI são gerados e verificados.
  Topologia, aplicações, amostragem e auditoria são responsabilidades separadas.
- F14 usa UDP multicast real. As tabelas dos switches são estáticas e incluem
  VLAN; entradas automáticas sem VLAN provocariam flooding do tráfego marcado.
- F21/F22 usam os dez pares medidos, amostragem uniforme com reposição e RNGs
  independentes. Sequências permanecem pareadas entre L/A com a mesma seed.
- O usuário confirmou que o volume das assinaturas é payload de aplicação:
  preservar bytes, usar payload máximo de 1472 B e corrigir a aproximação wire
  do P1 de 1542/1500 para 1542/1472 nos segmentos completos.
- A auditoria observa os quadros depois da inserção do preâmbulo; soma 12 B de
  IFG e verifica também o intervalo físico entre transmissões.
- O suporte de validação usa SP e buffers finitos nos switches. Talkers mantêm
  a fila FIFO de staging do INET, sem limite nesta etapa; isso não fecha C0–C4.
  Limitar uma fila de origem a 32 KiB ao liberar 30×1496 B simultaneamente
  descartaria parte da imagem antes da transmissão. A política das origens
  precisa ser definida na etapa de mecanismos, sem alterar o catálogo.
- Deadlines são medidos desde a geração; os contadores de medição usam coortes
  de geração e drenagem. Não são ainda a análise final de viabilidade do P1.
