#!/usr/bin/env python3
"""Run the 8 L/A cells, a new seed and all 10 signatures on the actual INET network."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / 'simulations'
sys.path.insert(0, str(ROOT / 'tests/validation/traffic'))
from check_traffic import check_run, check_pairing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inet-root', default=os.environ.get('INET_ROOT'))
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--skip-signatures', action='store_true')
    parser.add_argument('--check-existing', action='store_true', help='Recheck exported evidence without rerunning simulations')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if not args.inet_root and not args.check_existing:
        parser.error('Set INET_ROOT or pass --inet-root')
    inet = Path(args.inet_root or ".").resolve()
    output = SIM / 'results/traffic'
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/catalog/generate.py'), '--check'], check=True)
    configs = [f'Validate_L{level}_A{a}' for level in range(4) for a in range(2)] + ['ValidateReseed']
    if not args.skip_signatures:
        configs += ['ValidateSignatures']

    def run(config):
        command = [str(ROOT / 'src/zonal-ivn-tsn'), '-u', 'Cmdenv',
                   '-n', f'.:{ROOT / "src"}:{ROOT / "tests"}:{inet / "src"}',
                   '-f', 'omnetpp.ini', '-c', config, '--cmdenv-express-mode=true',
                   '--cmdenv-event-banners=false']
        log = output / f'{config}.log'
        if args.check_existing:
            check_run(output / f'{config}-0')
            print(f'PASS existing {config}', flush=True)
            return config
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=SIM, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode or '<!> Error:' in log.read_text() or 'Simulation time limit reached' not in log.read_text():
            raise RuntimeError(f'{config} failed: {log}')
        summary = check_run(output / f'{config}-0')
        print(f'PASS {config}: {summary["source_packets"]} generated, {summary["drops"]} recorded drops', flush=True)
        return config

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(run, configs))
    check_pairing(output)
    print(f'PASS paired L/A signatures, independent reseed and multicast. Results: {output}')


if __name__ == '__main__':
    main()
