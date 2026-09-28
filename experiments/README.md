# Plano experimental

`design.json` registra fatores e protocolo do P1; não executa simulações.
Seeds de calibração e piloto estão pendentes (`null`), devem ser definidos e
registrados antes do uso, sem sobreposição com os finais 1001–1030.

A matriz tem 40 células lógicas; C3/C4 em L3 são reservation-infeasible em A0 e A1.
Restam até 36 células/1.080 execuções; C4 ainda exige triagem de capacidade de gates.
Não recortar reservas nem reajustar CBS/GCL para forçar admissibilidade.
Separar calibração, piloto, congelamento e campanha final.

Cada execução futura deve registrar revisão do modelo, versões de dependências,
C/L/A/seed, durações, parâmetros CBS/TAS/gPTP resolvidos, sequência transitória,
status de admissibilidade, motivo de rejeição e eventual reexecução com a mesma seed.
Guardar saídas em `results/raw/`, `results/processed/` e `results/manifests/`
(ignorados pelo Git). Resultados desfavoráveis não justificam remoção de observações.
