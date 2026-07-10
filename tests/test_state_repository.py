from medexa.schemas import SessionState
from medexa.state import (
    FileSessionStateRepository,
    InMemorySessionStateRepository,
    SessionStateRepository,
)


def test_file_repo_import_and_roundtrip(tmp_path):
    repo = FileSessionStateRepository(tmp_path)
    assert isinstance(repo, SessionStateRepository)
    repo.save(SessionState(session_id="disk-1", status="active"))
    fetched = repo.get("disk-1")
    assert fetched is not None
    assert fetched.session_id == "disk-1"


def test_in_memory_repo_satisfies_protocol():
    repo = InMemorySessionStateRepository()
    assert isinstance(repo, SessionStateRepository)


def test_save_and_get_roundtrip():
    repo = InMemorySessionStateRepository()
    repo.save(SessionState(session_id="s1", status="active"))
    fetched = repo.get("s1")
    assert fetched is not None
    assert fetched.session_id == "s1"


def test_get_missing_returns_none():
    repo = InMemorySessionStateRepository()
    assert repo.get("nope") is None


def test_list_active_filters_by_status():
    repo = InMemorySessionStateRepository()
    repo.save(SessionState(session_id="a", status="active"))
    repo.save(SessionState(session_id="b", status="ended"))
    active_ids = {s.session_id for s in repo.list_active()}
    assert active_ids == {"a"}


def test_save_stores_isolated_copy():
    repo = InMemorySessionStateRepository()
    state = SessionState(session_id="s1", status="active")
    repo.save(state)
    # Mutating the original after save must not affect the stored copy.
    state.status = "ended"
    assert repo.get("s1").status == "active"


def test_delete_removes_session():
    repo = InMemorySessionStateRepository()
    repo.save(SessionState(session_id="s1", status="active"))
    repo.delete("s1")
    assert repo.get("s1") is None
