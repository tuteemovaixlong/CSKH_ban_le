#!/usr/bin/env python3
"""Case bootstrap and paired exact McNemar statistics, using only Python's standard library."""
import argparse
import copy
import json
import math
import random
from collections import defaultdict
from pathlib import Path

SEED = 20261110


def read_case_ids(path):
    """One ID per line; accept BOM/blank lines from shell redirection on Windows."""
    ids = [line.strip() for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    if not ids:
        raise ValueError('Case list is empty')
    if len(ids) != len(set(ids)):
        raise ValueError('Case list contains duplicate IDs')
    return ids


def subset(directory, size=100, seed=SEED):
    """Hamilton largest-remainder allocation, stable suite tie-break, seeded sampling."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('Subset DIR must be an existing directory')
    suites, seen = {}, set()
    for path in sorted(directory.glob('S*.jsonl')):
        ids = []
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            name = case['id']
            if not isinstance(name, str) or not name.strip() or name in seen:
                raise ValueError(f'{path.name}: invalid or duplicate case ID {name!r}')
            if case.get('meta', {}).get('suite') != path.stem:
                raise ValueError(f'{name}: meta.suite must equal {path.stem}')
            seen.add(name)
            ids.append(name)
        if ids:
            suites[path.stem] = sorted(ids)
    total = len(seen)
    if not 1 <= size <= total:
        raise ValueError(f'Subset size must be 1–{total}, got {size}')
    allocation = {suite: size * len(ids) // total for suite, ids in suites.items()}
    by_remainder = sorted(suites, key=lambda suite: (-(size * len(suites[suite]) % total), suite))
    for suite in by_remainder[:size - sum(allocation.values())]:
        allocation[suite] += 1
    rng = random.Random(seed)
    return [name for suite in sorted(suites) for name in sorted(rng.sample(suites[suite], allocation[suite]))]


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


def compare(left, right, cases=None):
    a, b = case_results(left), case_results(right)
    if cases is None and a.keys() != b.keys():
        raise ValueError('Reports have different case sets')
    def digests(report):
        if 'datasets' in report:
            return report['datasets']
        return {report['dataset']['path']: report['dataset']['sha256']}
    if digests(left) != digests(right):
        raise ValueError('Reports have different dataset SHA-256 digests')
    excluded = []
    if cases is not None:
        selected = set(cases) & a.keys() & b.keys()
        excluded = sorted(set(cases) - selected)
        if not selected:
            raise ValueError('Case list has no common cases in both reports')
        a, b = ({key: report[key] for key in sorted(selected)} for report in (a, b))
    # Strict majority; an even-K tie is a failure, recorded explicitly for reproducibility.
    majority = lambda runs: sum(bool(r['passed']) for r in runs) > len(runs) / 2
    wins = sum(majority(a[k]) and not majority(b[k]) for k in a)
    losses = sum(not majority(a[k]) and majority(b[k]) for k in a)
    result = {'cases': len(a), 'b': wins, 'c': losses, 'p_value': mcnemar_exact(wins, losses),
              'majority_tie': 'failure'}
    if cases is not None:
        result['excluded_case_ids'] = excluded
    return result


def merge_reports(reports):
    """Reject incompatible inputs before recomputing every aggregate from case/run records."""
    if not reports:
        raise ValueError('merge requires at least one report')
    required = {'git_sha', 'model', 'vllm_version', 'sampling', 'context_tokens',
                'thinking', 'agent_mode', 'knowledge'}
    def provenance(report):
        value = report.get('provenance')
        if not isinstance(value, dict) or not required <= value.keys():
            raise ValueError('missing or incomplete provenance')
        return {k: v for k, v in value.items() if k not in ('timestamp', 'started_at', 'finished_at', 'run_at')}
    first = reports[0]
    identity = provenance(first)
    if not first.get('datasets') or not first.get('config'):
        raise ValueError('missing dataset SHA-256 or runner config')
    seen, records = set(), []
    for report in reports:
        if provenance(report) != identity:
            raise ValueError('different provenance across shards')
        if report.get('datasets') != first['datasets']:
            raise ValueError('different dataset SHA-256 digests across shards')
        if any(report.get(k) != first.get(k) for k in ('config', 'mode', 'report', 'model')):
            raise ValueError('different runner config across shards')
        for row in report['scenarios']:
            pair = (row['id'], row.get('run'))
            if not isinstance(pair[0], str) or type(pair[1]) is not int or pair[1] < 1:
                raise ValueError('invalid case/run in shard')
            if pair in seen:
                raise ValueError(f'duplicate case/run pair: {pair}')
            seen.add(pair)
            records.append(copy.deepcopy(row))
    # Importable both from the repo and as `python scripts/eval_stats.py`.
    try:
        from scripts.run_agent_scenarios import report_from_records
    except ModuleNotFoundError:
        from run_agent_scenarios import report_from_records
    merged = copy.deepcopy(first)
    merged.update(report_from_records(sorted(records, key=lambda r: (r['id'], r['run'])), first['mode'], first['report']))
    merged['dataset']['scenarios'] = len({r['id'] for r in records})
    merged['merged_shards'] = len(reports)
    return merged


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('summary').add_argument('reports', nargs='+')
    merge_parser = commands.add_parser('merge')
    merge_parser.add_argument('out', type=Path)
    merge_parser.add_argument('reports', nargs='+')
    compare_parser = commands.add_parser('compare')
    compare_parser.add_argument('a')
    compare_parser.add_argument('b')
    compare_parser.add_argument('--cases', type=Path, help='compare listed IDs present in both reports')
    subset_parser = commands.add_parser('subset')
    subset_parser.add_argument('--size', type=int, default=100)
    subset_parser.add_argument('--seed', type=int, default=SEED)
    subset_parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    read = lambda path: json.loads(Path(path).read_text(encoding='utf-8'))
    try:
        if args.command == 'subset':
            print('\n'.join(subset(args.directory, args.size, args.seed)))
            return 0
        if args.command == 'merge':
            merged = merge_reports([read(path) for path in args.reports])
            # Replace atomically: an interrupted write is never mistaken for a completed report.
            target = args.out.with_name(args.out.name + '.tmp')
            with target.open('w', encoding='utf-8', newline='\n') as stream:
                stream.write(json.dumps(merged, ensure_ascii=False, indent=2) + '\n')
            target.replace(args.out)
            print(f'Merged {len(args.reports)} shards into {args.out}')
            return 0
        output = ({path: summary(read(path)) for path in args.reports} if args.command == 'summary'
                  else compare(read(args.a), read(args.b), cases=read_case_ids(args.cases) if args.cases else None))
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
