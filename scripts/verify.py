"""Run tests and regenerate actual examples without touching user runtime data."""
import argparse
import io
import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from scheduler.agent import run_agent
from scheduler.config import load_env_file
from scheduler.domain import validate_request
from scheduler.model import MockModel, OpenAICompatibleModel
from scheduler.tools import BusinessTools

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['mock', 'live'], default='mock')
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--out', type=Path, help='Optional fresh evidence directory')
    args = parser.parse_args()
    output = args.out or ROOT / 'examples' / args.mode
    output.mkdir(parents=True, exist_ok=True)
    fixture = json.loads((ROOT / 'data/fixtures.json').read_text(encoding='utf-8'))
    if args.mode == 'live':
        load_env_file(args.env_file)
    model = MockModel() if args.mode == 'mock' else OpenAICompatibleModel()
    cases = [
        ('normal', 'M01', '19', {}, 'completed'),
        ('missing', 'M02', '19', {}, 'incomplete'),
        ('risk', 'M03', '19', {}, 'blocked'),
        ('conflict', 'M01', '18', {}, 'pending_confirmation'),
        ('save_failure', 'M01', '19', {'fail_save': True}, 'save_failed'),
        ('metadata_recovery', 'M04', '19', {}, 'completed'),
        ('human_review', 'M05', '19', {}, 'review_required'),
        ('confirmed_alternative', 'M01', '18', {'confirmed_slot': '2026-11-01T19:00+08:00'}, 'completed'),
        ('no_available_slot', 'M01', '18', {'all_occupied': True}, 'incomplete'),
        ('changed_occupancy', 'M01', '18', {'changed_occupancy': True}, 'completed'),
        ('step_limit', 'M01', '19', {'max_steps': 1}, 'step_limit'),
    ]
    checks = []
    def record(name, request, tools, report):
        def write(suffix, value):
            (output / (name + suffix)).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        write('.input.json', request)
        write('.catalog.json', tools.fixture)
        write('.output.json', report)
        write('.trace.json', report['trace'])
        with tools.connect() as db:
            drafts = [json.loads(row[0]) for row in db.execute('SELECT payload FROM drafts ORDER BY request_id')]
            reservations = [{'slot': row[0], 'request_id': row[1]} for row in db.execute('SELECT slot,request_id FROM reservations ORDER BY slot')]
        write('.audit.json', {'draft_count': len(drafts), 'drafts': drafts, 'reservations': reservations})
    with tempfile.TemporaryDirectory() as temp:
        for name, asset, hour, config, expected in cases:
            request = validate_request({'request_id': 'example-' + name, 'asset_id': asset,
                'requested_slot': f'2026-11-01T{hour}:00+08:00', 'hard_requirement': True,
                **({'confirmed_slot': config['confirmed_slot']} if 'confirmed_slot' in config else {})})
            database = Path(temp) / (name + '.sqlite')
            tools = BusinessTools(request, fixture, database, config.get('fail_save', False))
            if config.get('all_occupied'):
                tools.fixture['occupied'] = list(tools.fixture['slots'])
            if config.get('changed_occupancy'):
                tools.fixture['occupied'] = ['2026-11-01T19:00+08:00']
            report = run_agent(request, model, tools, config.get('max_steps', 10))
            record(name, request, tools, report)
            checks.append({'case': name, 'expected': expected, 'actual': report['result']['status'],
                           'passed': report['result']['status'] == expected})
            if name == 'normal':
                duplicate_tools = BusinessTools(request, fixture, database)
                duplicate = run_agent(request, model, duplicate_tools)
                record('duplicate', request, duplicate_tools, duplicate)
                checks.append({'case': 'duplicate', 'expected': 'existing', 'actual': duplicate['result']['save']['save_status'],
                               'passed': duplicate['result']['save']['save_status'] == 'existing'})
            if name == 'conflict':
                confirmed_request = validate_request(dict(request, confirmed_slot='2026-11-01T19:00+08:00'))
                confirmed_tools = BusinessTools(confirmed_request, fixture, database)
                confirmed = run_agent(confirmed_request, model, confirmed_tools)
                record('confirm_pending', confirmed_request, confirmed_tools, confirmed)
                checks.append({'case': 'confirm_pending', 'expected': 'updated',
                               'actual': confirmed['result']['save']['save_status'],
                               'passed': confirmed['result']['save']['save_status'] == 'updated'
                                         and confirmed['result']['save'].get('draft_id') == report['result']['save'].get('draft_id')})
    stream = io.StringIO()
    tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / 'tests')))
    (output / 'tests.txt').write_text(stream.getvalue(), encoding='utf-8')
    hashes = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ('src', 'scripts', 'tests') for p in sorted((ROOT / folder).rglob('*.py'))}
    summary = {'generated_at': datetime.now(timezone.utc).isoformat(), 'mode': args.mode,
               'source_sha256': hashes,
               'real_model_verified': args.mode == 'live' and all(c['passed'] for c in checks), 'cases': checks, 'tests_run': tests.testsRun,
               'tests_passed': tests.wasSuccessful(), 'all_cases_passed': all(c['passed'] for c in checks)}
    (output / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if tests.wasSuccessful() and summary['all_cases_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
