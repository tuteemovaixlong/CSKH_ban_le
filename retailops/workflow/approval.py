"""Human approval graph: durable interrupt, then the existing atomic transaction."""
import re
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from retailops.business.permissions import CANCEL
from retailops.core import fields, require
from retailops.workflow.checkpoints import workflow


class ApprovalState(TypedDict):
    proposal: dict
    decision: dict
    result: dict


def proposal(store, customer, pid):
    with store.connection() as db:
        row = db.execute('SELECT * FROM proposals WHERE id=? AND customer_id=?', (pid, customer)).fetchone()
        require(row is not None, 404, 'proposal_not_found', 'Không tìm thấy đề xuất của bạn.')
        order = store.owned(db, customer, row['order_id'])
    return {'proposal_id': row['id'], 'order': order, 'reason': row['reason'],
            'order_version': row['order_version'], 'expires_at': row['expires_at'], 'state': row['state']}


def drive(app, customer, pid, decision=None):
    # Recheck role and ownership on EVERY resume, not only when creating the graph.
    app.require_permission(CANCEL)
    record = proposal(app.store, customer, pid)
    with workflow(app.store, customer, 'approval-v1', pid, pid, record,
                  expires_at=record['expires_at']+1800) as (saver, seed):
        def review(state):
            answer = interrupt({'kind': 'confirm_cancellation', 'proposal': state['proposal']})
            return {'decision': answer}

        def commit(state):
            chosen = state['decision']
            if chosen['approved']:
                result = app.store.confirm(customer, pid, {'confirmed': True}, chosen['key'])
            else:
                result = app.store.dismiss(customer, pid)
            return {'result': result}

        builder = StateGraph(ApprovalState)
        builder.add_node('review', review)
        builder.add_node('commit', commit)
        builder.add_edge(START, 'review')
        builder.add_edge('review', 'commit')
        builder.add_edge('commit', END)
        graph = builder.compile(checkpointer=saver)
        config = saver.config()
        current = graph.get_state(config)
        if not current.values:
            graph.invoke({'proposal': seed}, config, durability='sync')
            current = graph.get_state(config)
        if decision is None:
            return {**record, 'workflow_status': 'awaiting_confirmation'}
        previous = current.values.get('decision')
        require(previous is None or previous == decision, 409, 'idempotency_conflict',
                'Đề xuất đang xử lý một quyết định khác. Hãy tải lại trạng thái đơn.')
        result = graph.invoke(Command(resume=decision) if previous is None else None,
                              config, durability='sync') if current.next else current.values
        return result['result']


def confirm(app, customer, pid, body, key):
    app.require_permission(CANCEL)
    fields(body, {'confirmed'})
    require(body['confirmed'] is True, 400, 'confirmation_required', 'Cần xác nhận rõ ràng trước khi hủy.')
    require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key),
            400, 'idempotency_required', 'Thiếu mã chống thực hiện lặp.')
    # The transaction can commit just before a process dies saving its checkpoint.
    # The business record remains the authority, including the original request key.
    if proposal(app.store, customer, pid)['state'] == 'confirmed':
        return app.store.confirm(customer, pid, body, key)
    return drive(app, customer, pid, {'approved': True, 'key': key})


def dismiss(app, customer, pid):
    app.require_permission(CANCEL)
    if proposal(app.store, customer, pid)['state'] in ('dismissed', 'confirmed'):
        return app.store.dismiss(customer, pid)
    return drive(app, customer, pid, {'approved': False})
