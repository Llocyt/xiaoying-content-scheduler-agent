"""Business invariants live here, never in model-generated status text."""
import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from .domain import fingerprint, slot


class BusinessTools:
    def __init__(self, request, fixture, database, fail_save=False):
        self.request = request
        self.fixture = deepcopy(fixture)
        self.database = str(database)
        self.fail_save = fail_save
        self.asset = None
        self.review = None
        self.queried = {}
        self.saved = None
        self.save_attempted = False
        self.metadata_looked_up = False
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS drafts (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (slot TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def execute(self, name, args):
        if not isinstance(args, dict):
            return {'ok': False, 'error': 'arguments_must_be_object'}
        methods = {'read_asset': self.read_asset, 'lookup_metadata': self.lookup_metadata,
                   'check_rules': self.check_rules, 'query_slots': self.query_slots,
                   'save_draft': self.save_draft}
        if name not in methods:
            return {'ok': False, 'error': 'unknown_tool'}
        try:
            return methods[name](**args)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'invalid_arguments'}
        except sqlite3.Error:
            return {'ok': False, 'error': 'storage_error'}

    def read_asset(self, asset_id):
        if asset_id != self.request['asset_id']:
            return {'ok': False, 'error': 'asset_outside_request'}
        self.asset = deepcopy(self.fixture['assets'].get(asset_id))
        self.metadata_looked_up = False
        self.review = None
        if self.asset is None:
            return {'ok': False, 'error': 'asset_not_found'}
        return {'ok': True, 'asset': self.asset, 'missing': self.missing()}

    def missing(self):
        return [key for key in self.fixture['rules']['required_fields']
                if not self.asset or self.asset.get(key) in (None, '', [])]

    def lookup_metadata(self, asset_id):
        if asset_id != self.request['asset_id'] or self.asset is None:
            return {'ok': False, 'error': 'read_asset_first'}
        extra = self.fixture.get('metadata', {}).get(asset_id, {})
        self.metadata_looked_up = True
        for key, value in extra.items():
            if self.asset.get(key) in (None, '', []):
                self.asset[key] = value
        self.review = None
        return {'ok': True, 'asset': self.asset, 'missing': self.missing(), 'found': bool(extra)}

    def check_rules(self):
        if self.asset is None:
            return {'ok': False, 'error': 'read_asset_first'}
        reasons = []
        status = 'passed'
        if self.missing():
            status = 'incomplete'
            reasons.append('missing: ' + ', '.join(self.missing()))
        elif self.asset['rights'] != 'cleared':
            status = 'blocked'
            reasons.append('rights_not_cleared')
        else:
            text = self.asset['title'] + ' ' + self.asset['description']
            if any(term.casefold() in text.casefold() for term in self.fixture['rules']['blocked_terms']):
                status = 'blocked'
                reasons.append('prohibited_claim')
            elif self.asset.get('needs_human_review'):
                status = 'review_required'
                reasons.append('human_review_required')
        self.review = {'status': status, 'reasons': reasons}
        return {'ok': True, **self.review}

    def available(self, candidate, db=None):
        if candidate not in self.fixture['slots'] or candidate in self.fixture['occupied']:
            return False
        if db is None:
            with self.connect() as connection:
                return self.available(candidate, connection)
        row = db.execute('SELECT request_id FROM reservations WHERE slot=?', (candidate,)).fetchone()
        return row is None or row[0] == self.request['request_id']

    def query_slots(self, slot, alternatives=False):
        candidate = globals()['slot'](slot)
        if type(alternatives) is not bool:
            raise ValueError('alternatives must be boolean')
        if candidate[:10] != self.request['requested_slot'][:10]:
            return {'ok': False, 'error': 'outside_requested_day'}
        candidates = [candidate]
        if alternatives:
            candidates += [s for s in self.fixture['slots'] if s[:10] == candidate[:10] and s != candidate]
        result = [{'slot': s, 'available': self.available(s)} for s in candidates]
        self.queried.update({r['slot']: r['available'] for r in result})
        return {'ok': True, 'slots': result}

    def save_draft(self, slot):
        self.save_attempted = True
        candidate = globals()['slot'](slot)
        if not self.review or self.review['status'] != 'passed':
            return self.save_error('review_not_passed')
        # Re-read synthetic source and recheck rules at the write boundary.
        self.asset = deepcopy(self.fixture['assets'].get(self.request['asset_id']))
        if self.metadata_looked_up and self.asset:
            for key, value in self.fixture.get('metadata', {}).get(self.request['asset_id'], {}).items():
                if self.asset.get(key) in (None, '', []):
                    self.asset[key] = value
        if self.asset is None or self.check_rules().get('status') != 'passed':
            return self.save_error('review_changed_before_save')
        if candidate not in self.queried or not self.queried[candidate]:
            return self.save_error('query_available_slot_first')
        if candidate[:10] != self.request['requested_slot'][:10]:
            return self.save_error('outside_requested_day')
        needs_confirmation = (self.request['hard_requirement'] and candidate != self.request['requested_slot']
                              and candidate != self.request.get('confirmed_slot'))
        payload = {'draft_id': 'draft-' + fingerprint(self.request)[:16],
                   'asset_id': self.request['asset_id'], 'requested_slot': self.request['requested_slot'],
                   'suggested_slot': candidate, 'confirmation_status': 'pending' if needs_confirmation else 'confirmed',
                   'published': False}
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT fingerprint,payload FROM drafts WHERE request_id=?',
                                 (self.request['request_id'],)).fetchone()
                if row:
                    if row[0] != fingerprint(self.request):
                        return self.save_error('idempotency_key_conflict')
                    existing = json.loads(row[1])
                    if existing['suggested_slot'] != candidate:
                        return self.save_error('existing_draft_time_mismatch')
                    if existing['confirmation_status'] == 'confirmed' or needs_confirmation:
                        self.saved = {'ok': True, 'save_status': 'existing', **existing}
                        return deepcopy(self.saved)
                    if self.fail_save:
                        return self.save_error('simulated_storage_failure')
                    if not self.available(candidate, db):
                        return self.save_error('slot_became_unavailable')
                    db.execute('INSERT INTO reservations VALUES (?,?)', (candidate, self.request['request_id']))
                    db.execute('UPDATE drafts SET payload=? WHERE request_id=?',
                               (json.dumps(payload), self.request['request_id']))
                    self.saved = {'ok': True, 'save_status': 'updated', **payload}
                    return deepcopy(self.saved)
                if self.fail_save:
                    return self.save_error('simulated_storage_failure')
                if not self.available(candidate, db):
                    return self.save_error('slot_became_unavailable')
                db.execute('INSERT INTO drafts VALUES (?,?,?)', (self.request['request_id'], fingerprint(self.request), json.dumps(payload)))
                if not needs_confirmation:
                    db.execute('INSERT INTO reservations VALUES (?,?)', (candidate, self.request['request_id']))
            self.saved = {'ok': True, 'save_status': 'saved', **payload}
            return deepcopy(self.saved)
        except sqlite3.Error:
            return self.save_error('storage_error')

    def save_error(self, error):
        self.saved = {'ok': False, 'save_status': 'failed', 'error': error}
        return deepcopy(self.saved)

    def report(self, status, reason):
        review = self.review or {'status': 'not_checked', 'reasons': []}
        saved = self.saved or {'save_status': 'not_attempted'}
        if status == 'completed':
            if not self.saved or not self.saved.get('ok'):
                status = 'save_failed' if self.save_attempted else 'incomplete'
                if review['status'] in ('blocked', 'incomplete', 'review_required'):
                    status = review['status']
            elif saved['confirmation_status'] == 'pending':
                status = 'pending_confirmation'
        suggested = saved.get('suggested_slot')
        if suggested is None:
            suggested = next((s for s, free in self.queried.items() if free), None)
        pending = []
        if saved.get('confirmation_status') == 'pending':
            pending.append('confirm alternative time ' + saved['suggested_slot'] + '; resubmit SAME request_id with confirmed_slot')
        if review['status'] == 'incomplete':
            pending += review['reasons']
        if review['status'] == 'review_required':
            pending.append('human content review')
        summaries = {
            'completed': 'Draft persisted; no publishing performed.',
            'pending_confirmation': 'Alternative draft saved; original hard time unchanged; user confirmation required.',
            'save_failed': 'Draft save failed; inspect save.error.',
            'blocked': 'Content blocked by review rules; no draft saved.',
            'review_required': 'Human content review required; no draft saved.',
            'incomplete': 'Insufficient information, availability, or tool observations to complete scheduling.',
            'step_limit': 'Execution limit reached; work incomplete. Inspect save for any already persisted draft.',
            'model_error': 'Model unavailable or returned an invalid action; inspect trace error.',
        }
        return {'request_id': self.request['request_id'], 'asset_id': self.request['asset_id'],
                'status': status, 'review_status': review['status'], 'risk_reasons': review['reasons'],
                'requested_slot': self.request['requested_slot'], 'suggested_slot': suggested,
                'pending_items': pending, 'save': saved, 'published': False,
                'decision_summary': summaries[status]}
