"""Swappable decision adapters: real HTTP model or explicitly offline policy."""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit
from .domain import SYSTEM


class ModelError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError('model endpoint redirected; configure the final trusted URL')


class OpenAICompatibleModel:
    mode = 'live'

    def __init__(self):
        self.key = os.environ.get('MODEL_API_KEY', '')
        self.base = os.environ.get('MODEL_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
        self.model = os.environ.get('MODEL_NAME', '')
        if not self.key or not self.model:
            raise ModelError('MODEL_API_KEY and MODEL_NAME are required; no automatic mock fallback')
        try:
            parsed = urlsplit(self.base)
            valid = (parsed.scheme in ('http', 'https') and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and not parsed.query and not parsed.fragment)
            parsed.port  # Validate port without printing the possibly sensitive URL.
        except ValueError:
            valid = False
        if not valid:
            raise ModelError('invalid MODEL_BASE_URL; use an HTTP(S) endpoint without credentials, query or fragment')
        if (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1')
                and os.environ.get('MODEL_ALLOW_HTTP') != '1'):
            raise ModelError('remote HTTP requires explicit MODEL_ALLOW_HTTP=1; HTTPS is the default')
        # Accept a gateway origin as well as an explicit API prefix.
        self.base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or '/v1', '', ''))

    def decide(self, request, history):
        messages = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': json.dumps({'request': request, 'observations': history}, ensure_ascii=False)}]
        body = json.dumps({'model': self.model, 'messages': messages,
                           'response_format': {'type': 'json_object'}}).encode()
        req = urllib.request.Request(self.base + '/chat/completions', data=body,
                                     headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
                payload = json.load(response)
            return json.loads(payload['choices'][0]['message']['content'])
        except urllib.error.HTTPError as exc:
            raise ModelError(f'model HTTP {exc.code}; response body omitted to protect credentials') from None
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            raise ModelError('model connection or response format error') from None


class MockModel:
    """Deterministic simulation ONLY; not evidence of actual model reasoning."""
    mode = 'mock'

    def decide(self, request, history):
        def action(tool, reason, **arguments):
            return {'tool': tool, 'arguments': arguments, 'reason': reason}
        if not history:
            return action('read_asset', 'Read requested asset before review.', asset_id=request['asset_id'])
        last = history[-1]
        tool, result = last['tool'], last['observation']
        if not result.get('ok'):
            return action('finish', 'Tool failed; report observed failure without claiming completion.')
        if tool == 'read_asset' and result['missing']:
            return action('lookup_metadata', 'Missing metadata; check supplementary source.', asset_id=request['asset_id'])
        if tool in ('read_asset', 'lookup_metadata'):
            return action('check_rules', 'Check completeness, rights, and content policy.')
        if tool == 'check_rules':
            if result['status'] != 'passed':
                return action('finish', 'Review did not pass; stop scheduling and expose required action.')
            return action('query_slots', 'Review passed; check requested time.', slot=request['requested_slot'])
        if tool == 'query_slots':
            preferred = request.get('confirmed_slot', request['requested_slot'])
            free = [s['slot'] for s in result['slots'] if s['available']]
            if request.get('confirmed_slot') and preferred not in [s['slot'] for s in result['slots']]:
                return action('query_slots', 'Check explicitly confirmed alternative.', slot=preferred)
            if free:
                chosen = preferred if preferred in free else free[0]
                return action('save_draft', 'Save observed free time; tool enforces confirmation status.', slot=chosen)
            if not last['arguments'].get('alternatives'):
                return action('query_slots', 'Requested time is occupied; inspect alternatives.', slot=request['requested_slot'], alternatives=True)
            return action('finish', 'No free same-day slot; leave incomplete for user resolution.')
        return action('finish', 'Report actual draft save result; no publishing action exists.')
