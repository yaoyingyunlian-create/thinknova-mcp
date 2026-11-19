"""Prepare run-scoped image slots with stable task IDs and the existing quote/budget chain."""
import hashlib
import json
import re
import time
from pathlib import Path


def prepare_assets(client, claim, plan, directory, budget, quote, atomic):
    state_file = Path(directory) / 'asset-preparation.json'
    graph = plan.get('asset_preparation') or []
    digest = hashlib.sha256(json.dumps(graph, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    state = json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {'graph': digest, 'steps': {}}
    if state['graph'] != digest:
        raise RuntimeError('DAY_PLAN_PREPARATION_CHANGED')
    steps = state['steps']
    bindings = dict(plan.get('asset_bindings') or {})
    remote_steps = dict(claim.get('steps') or {})
    spent = 0

    def checkpoint():
        atomic(state_file, state)
        client.receipt(claim['run_no'], remote_steps)

    for position, item in enumerate(graph):
        slot = item['slot']
        if not re.fullmatch(r'slot_[a-z0-9_]{1,22}', slot):
            raise RuntimeError('DAY_PLAN_ASSET_SLOT_INVALID')
        current = steps.setdefault(slot, {})
        task_key, credit_key = 'asset_task_' + slot, 'asset_cost_' + slot
        if current.get('task') is None and remote_steps.get(task_key):
            current.update(task=remote_steps[task_key], credits=int(remote_steps[credit_key]))
        if slot not in bindings:
            args = current.get('arguments')
            if args is None:
                refs = [bindings.get(ref, ref) for ref in item['references']]
                if any(ref.startswith('slot_') for ref in refs):
                    raise RuntimeError('DAY_PLAN_ASSET_DEPENDENCY_MISSING')
                args = {'prompt': item['prompt'], 'ratio': item['ratio'], 'visual_subject': 'generic',
                        'client_request_id': claim['run_no'] + ':asset:' + slot,
                        'automation_run_id': claim['run_no'], 'project_key': plan['project_key']}
                if refs:
                    args['reference_asset_ids'] = refs
                tool = 'edit_image' if refs else 'generate_image'
                balance = client.tool('get_balance')
                if 'task' in current:
                    args['max_credits'] = int(current['credits'])
                else:
                    args = quote(client, tool, args, balance)
                    remaining_images = sum(int(step.get('estimated_credits', 0)) for step in graph[position + 1:])
                    forecast = args['max_credits'] + remaining_images + int(plan.get('minimum_video_credits', 0))
                    configuration, _ = client.post('/mcp/device/configuration', {})
                    remaining = (configuration.get('data') or {}).get('remaining_credits')
                    if type(remaining) is not int:
                        raise RuntimeError('DAY_PLAN_BUDGET_UNAVAILABLE')
                    if spent + forecast > budget or forecast > remaining:
                        raise RuntimeError('DAY_PLAN_OVER_BUDGET')
                    if forecast > int(balance.get('available_credits', 0)):
                        raise RuntimeError('DAY_PLAN_INSUFFICIENT_CREDITS')
                current.update(arguments=args, credits=args['max_credits'], tool=tool)
                checkpoint()
            if 'task' not in current:
                created = client.tool(current['tool'], args)
                current['task'] = created['task_id']
                remote_steps[task_key] = current['task']
                remote_steps[credit_key] = str(current['credits'])
                checkpoint()
            deadline = time.monotonic() + 900
            while True:
                task = client.tool('get_task', {'task_id': current['task']})
                if task['status'] == 'succeeded':
                    break
                if task['status'] in ('failed', 'canceled', 'cancelled'):
                    raise RuntimeError('DAY_PLAN_ASSET_GENERATION_FAILED')
                if time.monotonic() >= deadline:
                    client.receipt(claim['run_no'], remote_steps, 'pending', 'DAY_PLAN_ASSET_PENDING')
                    raise RuntimeError('DAY_PLAN_ASSET_PENDING')
                checkpoint()
                time.sleep(10)
            response, _ = client.post('/mcp/device/day-plan/materialize', {
                'run_no': claim['run_no'], 'bindings': {slot: current['task']}})
            plan = response['data']['plan']
            bindings = dict(plan['asset_bindings'])
        spent += int(current.get('credits', remote_steps.get(credit_key, 0)))
    plan['preparation_credits'] = max(spent, int(plan.get('preparation_credits', 0)))
    claim['steps'] = remote_steps
    atomic(Path(directory) / 'prepared-day-plan.json', plan)
    return plan
