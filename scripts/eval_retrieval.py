#!/usr/bin/env python3
"""Recall@3 and reciprocal rank through the actual bounded KnowledgeTool."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def evaluate(cases, store):
    from retailops.knowledge.tool import KnowledgeTool
    rows = []
    for case in cases:
        first = case['turns'][0]
        expected = set(first['expect'].get('sources', []))
        if not expected:
            continue
        result = KnowledgeTool(store).search(first['user'])
        found = list(dict.fromkeys(r['source_key'] for r in result.get('results', [])))[:3]
        ranks = [i for i, key in enumerate(found, 1) if key in expected]
        rows.append(dict(id=case['id'], query=first['user'], expected=sorted(expected), retrieved=found,
                         recall_at_3=len(expected & set(found)) / len(expected),
                         reciprocal_rank=1 / min(ranks) if ranks else 0., error=result.get('error')))
    return {'cases': len(rows), 'recall_at_3': sum(r['recall_at_3'] for r in rows) / len(rows) if rows else None,
            'mrr': sum(r['reciprocal_rank'] for r in rows) / len(rows) if rows else None, 'results': rows}


def main(argv=None):
    from scripts.eval_knowledge import RealKnowledge
    from scripts.run_agent_scenarios import load_dataset, dataset_digest, _checker
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--dataset', type=Path)
    source.add_argument('--dataset-dir', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    cases = _checker().validate_suites(args.dataset_dir) if args.dataset_dir else load_dataset(args.dataset)
    paths = sorted(args.dataset_dir.glob('S*.jsonl')) if args.dataset_dir else [args.dataset]
    with RealKnowledge() as real:
        report = evaluate(cases, real.store)
    report['datasets'] = {path.name: dataset_digest(path) for path in paths}
    print('id | Recall@3 | reciprocal rank')
    for row in report['results']:
        print(f"{row['id']} | {row['recall_at_3']:.4f} | {row['reciprocal_rank']:.4f}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
