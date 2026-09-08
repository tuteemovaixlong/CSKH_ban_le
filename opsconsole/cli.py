"""Offline routing evaluation and import of previously measured live E2E results."""
import argparse
import sys
from pathlib import Path
from opsconsole.evaluation import router_report, import_live, save_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('router', 'import-live'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--commit', default='unknown')
    args = parser.parse_args()
    if args.mode == 'router':
        from agent_protocol import request_mode
        result = router_report(args.source, request_mode, args.commit)
    else:
        result = import_live(args.source)
    target = save_report(result, args.out)
    print('EVALUATION_SAVED', target.name, 'cases=' + str(result['metrics']['cases']),
          'passed=' + str(result['metrics']['passed']))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError):
        print('EVALUATION_FAILED: invalid input or artifact write failure', file=sys.stderr)
        raise SystemExit(1)
