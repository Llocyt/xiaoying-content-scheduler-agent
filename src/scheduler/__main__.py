import argparse
import json
import sys
from pathlib import Path
from .agent import run_agent
from .config import load_env_file
from .domain import validate_request
from .model import MockModel, ModelError, OpenAICompatibleModel
from .tools import BusinessTools


def main():
    parser = argparse.ArgumentParser(description='Review content and save schedule DRAFTS only.')
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--mode', choices=['mock', 'live'], default='mock')
    parser.add_argument('--env-file', type=Path, default=Path('.env'), help='Live model configuration; environment variables take precedence.')
    parser.add_argument('--data', type=Path, default=Path('data/fixtures.json'))
    parser.add_argument('--db', type=Path, default=Path('.runtime/drafts.sqlite'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--max-steps', type=int, default=10)
    parser.add_argument('--fail-save', action='store_true', help='Simulate storage failure (test only).')
    args = parser.parse_args()
    try:
        if args.output:
            for protected in (args.input, args.data, args.db):
                if (args.output.resolve() == protected.resolve()
                        or (args.output.exists() and protected.exists() and args.output.samefile(protected))):
                    raise ValueError('output must not overwrite input, catalog, or database')
        request = validate_request(json.loads(args.input.read_text(encoding='utf-8')))
        fixture = json.loads(args.data.read_text(encoding='utf-8'))
        if args.mode == 'live':
            load_env_file(args.env_file)
        model = MockModel() if args.mode == 'mock' else OpenAICompatibleModel()
        tools = BusinessTools(request, fixture, args.db, args.fail_save)
        report = run_agent(request, model, tools, args.max_steps)
        text = json.dumps(report, ensure_ascii=False, indent=2)
        print(text)
        if args.output:
            try:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text + '\n', encoding='utf-8')
            except OSError:
                print(json.dumps({'status': 'artifact_error', 'error': 'output_write_failed',
                                  'detail': 'Business result is preserved on stdout; a draft may already exist.'}), file=sys.stderr)
                return 2
        return 0 if report['result']['status'] in ('completed', 'pending_confirmation', 'blocked', 'review_required') else 2
    except (ValueError, TypeError, OSError, KeyError, ModelError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
