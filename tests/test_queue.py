"""Unit tests for RequestQueue and SessionStore."""

from ag_attention_bridge.domain.models import (
    InteractionOption,
    InteractionRequest,
    RequestStatus,
    RequestType,
)
from ag_attention_bridge.state.store import RequestQueue, SessionStore


def make_request(
    request_id: str,
    conversation_id: str = "conv-1",
    title: str = "Test Title",
    body: str = "Test Body",
) -> InteractionRequest:
    return InteractionRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        request_type=RequestType.QUESTION,
        title=title,
        body=body,
        options=[InteractionOption(id="1", label="Option 1")],
    )


def test_queue_enqueue_and_fifo_order():
    counts = []
    queue = RequestQueue(on_count_changed=lambda c: counts.append(c))

    req1 = make_request("req-1", title="First")
    req2 = make_request("req-2", title="Second")

    assert queue.enqueue(req1) is True
    assert queue.enqueue(req2) is True
    assert queue.count() == 2
    assert counts == [1, 2]

    active = queue.get_active()
    assert active is not None
    assert active.request_id == "req-1"


def test_queue_deduplication():
    queue = RequestQueue()

    req1 = make_request("req-1", title="Duplicate Title", body="Same Body")
    req2 = make_request("req-2", title="Duplicate Title", body="Same Body")

    assert queue.enqueue(req1) is True
    # Identical content fingerprint should be deduplicated
    assert queue.enqueue(req2) is False
    assert queue.count() == 1


def test_queue_resolve_and_consume():
    counts = []
    queue = RequestQueue(on_count_changed=lambda c: counts.append(c))

    req = make_request("req-1")
    queue.enqueue(req)
    assert queue.count() == 1

    # Resolve does not immediately remove from pending list until consumed
    resolved = queue.resolve("req-1", "My Answer")
    assert resolved is not None
    assert resolved.status == RequestStatus.ANSWERED
    assert resolved.response_value == "My Answer"
    assert queue.count() == 1

    # Consume removes from pending queue
    consumed = queue.consume("req-1")
    assert consumed is not None
    assert consumed.status == RequestStatus.CONSUMED
    assert queue.count() == 0
    assert counts == [1, 0]


def test_queue_dismiss_to_tray_leaves_pending():
    queue = RequestQueue()
    req = make_request("req-1")
    queue.enqueue(req)

    queue.dismiss_to_tray("req-1")
    assert queue.count() == 1
    assert queue.get_active() is not None


def test_session_store_multi_session_isolation():
    store = SessionStore()

    s1 = store.get_or_create("conv-alpha", workspace_paths=["/path/a"])
    s2 = store.get_or_create("conv-beta", workspace_paths=["/path/b"])

    assert s1.conversation_id == "conv-alpha"
    assert s2.conversation_id == "conv-beta"
    assert s1.workspace_paths == ["/path/a"]
    assert s2.workspace_paths == ["/path/b"]

    store.attach_request("conv-alpha", "req-alpha-1")
    store.attach_request("conv-beta", "req-beta-1")

    assert "req-alpha-1" in s1.requests
    assert "req-alpha-1" not in s2.requests
    assert "req-beta-1" in s2.requests
