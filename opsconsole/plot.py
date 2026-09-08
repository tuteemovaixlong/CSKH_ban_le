"""Optional PNG artifact rendering; matplotlib is not a server dependency."""
import argparse
from pathlib import Path
from opsconsole.evaluation import load_json, SCHEMA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    report = load_json(args.report)
    if report.get('schema') != SCHEMA:
        raise ValueError('Unsupported evaluation schema')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    def bars(filename, title, values, ylabel):
        if not values:
            return
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.bar([x[0] for x in values], [x[1] for x in values])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis='x', rotation=25)
        fig.tight_layout()
        fig.savefig(target / filename, dpi=150)
        plt.close(fig)
    bars('category-pass.png', report['kind'] + ': contract pass rate (not answer accuracy)',
         [(k, v['pass_rate'] * 100) for k, v in report['metrics']['by_category'].items() if v['pass_rate'] is not None], 'Percent')
    bars('latency.png', 'Measured trace latency (no unmeasured cases)',
         [(c['id'], c['trace']['latency_ms']) for c in report['cases'] if c.get('trace') and c['trace']['latency_ms'] is not None], 'Milliseconds')
    matrix = report['metrics']['routing']
    if matrix['n']:
        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        ax.imshow(matrix['confusion_matrix'])
        ax.set_xticks(range(3), matrix['predicted_labels'])
        ax.set_yticks(range(2), matrix['actual_labels'])
        ax.set_xlabel('Predicted')
        ax.set_ylabel('Expected')
        ax.set_title('Router confusion matrix / n=' + str(matrix['n']))
        for i, row in enumerate(matrix['confusion_matrix']):
            for j, val in enumerate(row):
                ax.text(j, i, str(val), ha='center', va='center')
        fig.tight_layout()
        fig.savefig(target / 'router-confusion.png', dpi=150)
        plt.close(fig)
    print('EVALUATION_PLOTS_SAVED')


if __name__ == '__main__':
    main()
