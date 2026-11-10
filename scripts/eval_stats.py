#!/usr/bin/env python3
"""Case bootstrap and paired exact McNemar statistics, using only Python's standard library."""
import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

SEED = 20261110


def bootstrap_ci(values, samples=10000, seed=SEED):
    if not values:
        return [None, None]
    rng, n = random.Random(seed), len(values)
    estimates = sorted(sum(rng.choices(values, k=n)) / n for _ in range(samples))
    return (estimates[math.floor(.025 * samples)], estimates[math.ceil(.975 * samples) - 1])


def mcnemar_exact(b, c):
    if b < 0 or c < 0:
        raise ValueError('Discordant counts must be nonnegative')
    n = b + c
    return min(1., 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n) if n else 1.


def case_results(report):
    groups = defaultdict(list)
    for row in report['scenarios']:
        groups[row['id']].append(row)
    return groups


def summarize_group(groups):
    values = [sum(bool(r['passed']) for r in runs) / len(runs) for runs in groups.values()]
    return {'cases': len(groups), 'pass_at_1': sum(values) / len(values) if values else None,
            'ci_95': bootstrap_ci(values),
            'pass_power_k': sum(all(r['passed'] for r in runs) for runs in groups.values()) / len(groups) if groups else None}


def summary(report):
    groups = case_results(report)
    result = summarize_group(groups)
    for dimension in ('suite', 'origin'):
        subsets = defaultdict(dict)
        for case_id, runs in groups.items():
            key = runs[0].get('meta', {}).get(dimension, runs[0].get('category') if dimension == 'suite' else 'unknown')
            subsets[key][case_id] = runs
        result['by_' + dimension] = {key: summarize_group(rows) for key, rows in sorted(subsets.items())}
    return result


def compare(left, right):
    a, b = case_results(left), case_results(right)
    if a.keys() != b.keys():
        raise ValueError('Reports have different case sets')
    def digests(report):
        if 'datasets' in report:
            return report['datasets']
        return {report['dataset']['path']: report['dataset']['sha256']}
    if digests(left) != digests(right):
        raise ValueError('Reports have different dataset SHA-256 digests')
    # Strict majority; an even-K tie is a failure, recorded explicitly for reproducibility.
    majority = lambda runs: sum(bool(r['passed']) for r in runs) > len(runs) / 2
    wins = sum(majority(a[k]) and not majority(b[k]) for k in a)
    losses = sum(not majority(a[k]) and majority(b[k]) for k in a)
    return {'cases': len(a), 'b': wins, 'c': losses, 'p_value': mcnemar_exact(wins, losses),
            'majority_tie': 'failure'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('summary').add_argument('reports', nargs='+')
    compare_parser = commands.add_parser('compare')
    compare_parser.add_argument('a')
    compare_parser.add_argument('b')
    args = parser.parse_args(argv)
    read = lambda path: json.loads(Path(path).read_text(encoding='utf-8'))
    try:
        output = ({path: summary(read(path)) for path in args.reports} if args.command == 'summary'
                  else compare(read(args.a), read(args.b)))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
