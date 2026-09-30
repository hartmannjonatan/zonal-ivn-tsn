# Compilação e execução

- `build.sh`: verifica os artefatos gerados, regenera o Makefile de `src` via
  opp_makemake e compila o executável. Requer ambiente OMNeT++ e INET_ROOT.
- `validate_traffic.py`: executa e confere a matriz L/A, outra seed e todas as
  assinaturas. `--check-existing` confere as evidências sem repetir a simulação.
- `simulations/run`: launcher que fixa o diretório de trabalho e os caminhos NED.

Ver `tests/validation/traffic/README.md` para comandos e resultados.
Ainda não há executor da campanha C0–C4 final, calibração ou triagem CBS/TAS.
Seeds de diagnóstico 41/42 não se confundem com as seeds finais 1001–1030.
