#!/usr/bin/env bash
set -euo pipefail
: "${INET_ROOT:?Set INET_ROOT to the INET 4.7.0 installation and load OMNeT++ setenv}"
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
python3 "$project_dir/scripts/catalog/generate.py" --check
cd "$project_dir/src"
opp_makemake -f --deep -o zonal-ivn-tsn -DINET_IMPORT \
  -I"$INET_ROOT/src" -L"$INET_ROOT/src" '-lINET$(D)'
make MODE="${MODE:-release}" -j"${BUILD_JOBS:-2}"
