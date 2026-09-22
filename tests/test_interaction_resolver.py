"""Unit tests for InteractionResolver state machine, idempotency guards, and error states."""

from __future__ import annotations

import pytest

from ag_attention_bridge.antigravity.errors import (
    InteractionStaleError,
    InteractionSubmissionError,
)
from ag_attention_bridge.antigravity.interaction_resolver import InteractionResolver
from ag_attention_bridge.antigravity.models import (
    AntigravityServer,
    PermissionScope,
    QuestionEntry,
    SubmissionState,
)


class MockClient:
    def __init__(self, server=None):
        self.server = server or AntigravityServer(
            pid=1, workspace_id="ws", https_port=4000, csrf_token="tok"
        )
        self.submissions = []
        self.should_fail = False
        self.should_be_stale = False

    def build_ask_question_payload(self, trajectory_id, step_index, responses, cancelled=False):
        return {"trajectoryId": trajectory_id, "stepIndex": step_index, "askQuestion": {}}

    def build_permission_payload(
        self,
        trajectory_id,
        step_index,
        allow,
        scope=PermissionScope.PERMISSION_SCOPE_ONCE,
        user_deny_instruction="",
    ):
        return {
            "trajectoryId": trajectory_id,
            "stepIndex": step_index,
            "permission": {"allow": allow},
        }

    def handle_cascade_user_interaction(self, cascade_id, payload):
        if self.should_be_stale:
            raise InteractionStaleError("Step already resolved")
        if self.should_fail:
            raise RuntimeError("Connection dropped")
        self.submissions.append((cascade_id, payload))
        return {"status": "ok"}

    def find_waiting_interaction(self, cascade_id, max_retries=5, retry_delays=None):
        return ("traj-auto-1", 7, {"status": "CORTEX_STEP_STATUS_WAITING"})


class MockDiscovery:
    def __init__(self, servers=None):
        self._servers = servers or [
            AntigravityServer(pid=1, workspace_id="ws", https_port=4000, csrf_token="tok")
        ]

    def discover_servers(self, force=False):
        return self._servers

    def find_server_for_workspace(self, workspace_path):
        return self._servers[0] if self._servers else None


def test_duplicate_submission_guard():
    """Verify that duplicate submissions for the same (cascade, traj, step) are blocked."""
    mock_client = MockClient()
    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[1] = mock_client

    responses = [QuestionEntry(question="Q?", options=[], selected_option_ids=["1"])]

    # 1. First submission succeeds
    ok1 = resolver.submit_question_response("c1", "t1", 5, responses)
    assert ok1 is True
    assert resolver.get_state("c1", "t1", 5) == SubmissionState.SUBMITTED
    assert len(mock_client.submissions) == 1

    # 2. Second submission must be blocked by idempotency guard
    ok2 = resolver.submit_question_response("c1", "t1", 5, responses)
    assert ok2 is False
    assert len(mock_client.submissions) == 1  # No second RPC call made


def test_permission_submission_success():
    """Verify permission decision submission and state update."""
    mock_client = MockClient()
    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[1] = mock_client

    ok = resolver.submit_permission_decision(
        cascade_id="c2",
        trajectory_id="t2",
        step_index=3,
        allow=True,
        scope=PermissionScope.PERMISSION_SCOPE_CONVERSATION,
    )
    assert ok is True
    assert resolver.get_state("c2", "t2", 3) == SubmissionState.SUBMITTED
    assert len(mock_client.submissions) == 1


def test_stale_interaction_state_transition():
    """Verify state transitions to STALE when server rejects with stale interaction error."""
    mock_client = MockClient()
    mock_client.should_be_stale = True
    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[1] = mock_client

    with pytest.raises(InteractionStaleError):
        resolver.submit_question_response("c3", "t3", 10, [])

    assert resolver.get_state("c3", "t3", 10) == SubmissionState.STALE


def test_failed_interaction_state_transition():
    """Verify state transitions to FAILED on unrecoverable RPC exception."""
    mock_client = MockClient()
    mock_client.should_fail = True
    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[1] = mock_client

    with pytest.raises(InteractionSubmissionError):
        resolver.submit_permission_decision("c4", "t4", 2, allow=False)

    assert resolver.get_state("c4", "t4", 2) == SubmissionState.FAILED


def test_submit_interaction_auto_resolves_trajectory():
    """Verify unified submit_interaction auto-resolves trajectory_id and step_index if missing."""
    mock_client = MockClient()
    resolver = InteractionResolver(discovery=MockDiscovery())
    resolver._client_cache[1] = mock_client

    # Pass trajectory_id=None, step_index=None
    ok = resolver.submit_interaction(
        cascade_id="c-auto",
        trajectory_id=None,
        step_index=None,
        is_permission=True,
        response_data={"allow": True},
    )
    assert ok is True
    # Auto-resolved trajectory traj-auto-1 and step 7
    assert resolver.get_state("c-auto", "traj-auto-1", 7) == SubmissionState.SUBMITTED


def test_invalidate_client_cache():
    """Verify client cache can be selectively or globally cleared."""
    resolver = InteractionResolver(discovery=MockDiscovery())
    c1 = MockClient()
    c2 = MockClient()
    resolver._client_cache[101] = c1
    resolver._client_cache[102] = c2

    # Invalidate specific PID
    resolver.invalidate_client_cache(101)
    assert 101 not in resolver._client_cache
    assert 102 in resolver._client_cache

    # Invalidate all
    resolver.invalidate_client_cache()
    assert len(resolver._client_cache) == 0


def test_multi_server_candidate_selection_prioritizes_freshest_and_waiting():
    """Verify that candidate selection prioritizes the server with the freshest trajectory and waiting step."""
    s1 = AntigravityServer(pid=1001, workspace_id="ws1", https_port=4001, csrf_token="tok1")
    s2 = AntigravityServer(pid=1002, workspace_id="ws2", https_port=4002, csrf_token="tok2")

    c1 = MockClient(server=s1)
    c1.get_cascade_trajectory = lambda cid: {
        "trajectory": {
            "cascadeId": cid,
            "steps": [{"status": "DONE"} for _ in range(10)],
        }
    }

    c2 = MockClient(server=s2)
    c2.get_cascade_trajectory = lambda cid: {
        "trajectory": {
            "cascadeId": cid,
            "steps": [{"status": "DONE"} for _ in range(25)]
            + [{"status": "WAITING", "requestedInteraction": {"askQuestion": {}}}],
        }
    }

    disc = MockDiscovery(servers=[s1, s2])
    resolver = InteractionResolver(discovery=disc)
    resolver._client_cache[1001] = c1
    resolver._client_cache[1002] = c2

    winner = resolver._get_client_for_cascade("target-cascade")
    assert winner.server.pid == 1002
    assert winner is c2


def test_scan_waiting_interactions():
    """Verify that scan_waiting_interactions finds cascades with needsAttention: true."""
    s1 = AntigravityServer(pid=2001, workspace_id="ws-scan", https_port=4003, csrf_token="tok3")
    c1 = MockClient(server=s1)
    c1.search_conversations = lambda query="": [
        {"cascadeId": "active-1", "title": "Review", "needsAttention": True},
        {"cascadeId": "idle-2", "title": "Done", "needsAttention": False},
    ]
    c1.find_waiting_interaction = lambda cid, max_retries=5, retry_delays=None: (
        "traj-scan-1",
        0,
        {
            "status": "WAITING",
            "type": "CORTEX_STEP_TYPE_RUN_COMMAND",
            "requestedInteraction": {
                "permission": {
                    "resource": {"action": "command", "target": "ls -la"},
                    "actionDescription": "List files",
                }
            },
        },
    )

    disc = MockDiscovery(servers=[s1])
    resolver = InteractionResolver(discovery=disc)
    resolver._client_cache[2001] = c1

    results = resolver.scan_waiting_interactions()
    assert len(results) == 1
    cid, resolved = results[0]
    assert cid == "active-1"
    assert resolved["permission_action"] == "command"
    assert resolved["permission_target"] == "ls -la"
    assert resolved["permission_reason"] == "List files"
