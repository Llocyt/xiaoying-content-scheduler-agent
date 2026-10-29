"""Bounded model -> tool -> observation -> model loop."""
from datetime import datetime, timezone
from .model import ModelError


def run_agent(request, model, tools, max_steps=10):
    if type(max_steps) is not int or not 1 <= max_steps <= 30:
        raise ValueError('max_steps must be between 1 and 30')
    trace = []
    state, reason = 'step_limit', 'Execution limit reached; work is incomplete.'
    for step in range(1, max_steps + 1):
        try:
            decision = model.decide(request, trace)
        except ModelError as exc:
            state, reason = 'model_error', str(exc)
            trace.append({'step': step, 'error': reason})
            break
        if (not isinstance(decision, dict) or set(decision) != {'tool', 'arguments', 'reason'}
                or not isinstance(decision['tool'], str) or not isinstance(decision['arguments'], dict)
                or not isinstance(decision['reason'], str) or len(decision['reason']) > 1000):
            state, reason = 'model_error', 'Invalid model action schema.'
            trace.append({'step': step, 'error': reason})
            break
        name, args = decision['tool'], decision['arguments']
        if name == 'finish':
            trace.append({'step': step, **decision, 'observation': {'ok': True, 'loop_finished': True}})
            state, reason = 'completed', decision['reason']
            break
        observation = tools.execute(name, args)
        trace.append({'step': step, **decision, 'observation': observation})
    for index, event in enumerate(trace):
        event['next_action'] = trace[index + 1].get('tool', 'execution_error') if index + 1 < len(trace) else 'end:' + state
    return {'schema_version': 1, 'mode': model.mode, 'model': getattr(model, 'model', 'deterministic-offline-policy'),
            'started_or_finished_at': datetime.now(timezone.utc).isoformat(),
            'max_steps': max_steps, 'steps_used': len(trace), 'input': request,
            'result': tools.report(state, reason), 'trace': trace}
