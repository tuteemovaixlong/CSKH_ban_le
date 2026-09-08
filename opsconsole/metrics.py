"""Observable measurements only: missing data is null, not a successful score."""
from __future__ import annotations
import math
from collections import Counter

MODES = ('general', 'retail')
TOOLS = frozenset(('get_order', 'list_orders', 'get_product', 'search_products',
                   'get_context', 'search_knowledge', 'prepare_cancellation',
                   'get_runtime_info', 'get_current_time'))


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def ratio(a, b):
    return a / b if b else None


def classification(pairs):
    rows = list(pairs)
    if any(actual not in MODES for actual, _ in rows):
        raise ValueError('Unknown expected routing label')
    matrix = [[0, 0, 0], [0, 0, 0]]
    for actual, predicted in rows:
        matrix[MODES.index(actual)][MODES.index(predicted) if predicted in MODES else 2] += 1
    classes = {}
    for i, name in enumerate(MODES):
        tp, support = matrix[i][i], sum(matrix[i])
        predictions = sum(r[i] for r in matrix)
        classes[name] = {'precision': ratio(tp, predictions), 'recall': ratio(tp, support),
                         'f1': ratio(2 * tp, support + predictions), 'support': support}
    f1s = [v['f1'] for v in classes.values() if v['f1'] is not None]
    return {'n': len(rows), 'accuracy': ratio(sum(matrix[i][i] for i in range(2)), len(rows)),
            'macro_f1': sum(f1s) / len(f1s) if f1s else None, 'classes': classes,
            'actual_labels': list(MODES), 'predicted_labels': [*MODES, 'unknown'],
            'confusion_matrix': matrix, 'unknown_predictions': sum(r[2] for r in matrix)}


def distribution(values):
    values = sorted(v for v in values if number(v) is not None)
    def percentile(p):
        position = (len(values) - 1) * p
        lower, upper = math.floor(position), math.ceil(position)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    n = len(values)
    return {'n': n, 'mean': sum(values) / n if n else None,
            'p50': percentile(.5) if n else None,
            'p95': percentile(.95) if n >= 20 else None,
            'p99': percentile(.99) if n >= 100 else None,
            'tail_policy': 'p95 requires >=20 observations; p99 requires >=100; descriptive only'}


def observed_sum(values):
    values = list(values)
    known = [v for v in values if number(v) is not None]
    return {'known_sum': sum(known) if known else None, 'known_count': len(known),
            'total_count': len(values), 'coverage': ratio(len(known), len(values))}


def trace_metrics(traces):
    traces = list(traces)
    return {'n': len(traces), 'latency_ms': distribution(t.get('latency_ms') for t in traces),
            **{key: observed_sum(t.get(key) for t in traces)
               for key in ('model_calls', 'prompt_tokens', 'generated_tokens', 'reported_cost_usd')},
            'tool_calls': dict(Counter(name for t in traces for name in t.get('tools', []))),
            'note': 'Recorded trace usage, not a billing ledger. Missing cost is unknown; no infrastructure cost inferred.'}


def retrieval(ranked_ids, relevance, k):
    """IR metrics require explicit qrels; never infer relevance from citations."""
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError('k must be positive')
    if relevance is None:
        return {'precision_at_k': None, 'recall_at_k': None, 'mrr_at_k': None, 'ndcg_at_k': None}
    if not isinstance(relevance, dict) or any(number(v) is None for v in relevance.values()):
        raise ValueError('Invalid relevance judgments')
    seen = set()
    ranking = []
    for value in ranked_ids:
        if value not in seen:
            seen.add(value)
            ranking.append(value)
    top = ranking[:k]
    relevant = {key for key, grade in relevance.items() if grade > 0}
    hits = len(set(top) & relevant)
    dcg = sum(relevance.get(key, 0) / math.log2(i + 2) for i, key in enumerate(top))
    ideal = sum(grade / math.log2(i + 2) for i, grade in enumerate(sorted(relevance.values(), reverse=True)[:k]))
    return {'precision_at_k': hits / k, 'recall_at_k': ratio(hits, len(relevant)),
            'mrr_at_k': next((1 / (i + 1) for i, key in enumerate(top) if key in relevant), 0.0) if relevant else None,
            'ndcg_at_k': ratio(dcg, ideal)}
