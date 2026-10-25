import json
import os

import pytest

from bingo.storage import JsonStore, StorageError, UserAuth


@pytest.fixture
def store(tmp_path):
    return JsonStore(str(tmp_path / "bets.json"))


def test_missing_and_empty_file_are_empty(store):
    assert store.get("a", []) == []
    open(store.path, "w").close()
    assert store.get("a", []) == []


def test_set_keeps_other_users(store):
    store.set("a", [1])
    store.set("b", [2])
    assert json.load(open(store.path)) == {"a": [1], "b": [2]}


def test_corrupted_file_is_never_overwritten(store):
    open(store.path, "w").write('{"a": [1], "b": [')
    with pytest.raises(StorageError):
        store.set("c", [])
    assert open(store.path).read() == '{"a": [1], "b": ['
    assert not [f for f in os.listdir(os.path.dirname(store.path)) if f.endswith(".tmp")]


def test_non_dict_file_is_rejected(store):
    open(store.path, "w").write("[1, 2]")
    with pytest.raises(StorageError):
        store.get("a")


def test_user_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(UserAuth, "store", JsonStore(str(tmp_path / "users.json")))
    monkeypatch.setattr(UserAuth, "ITERATIONS", 1000)
    assert not UserAuth.has_password("amy") and UserAuth.verify("amy", "")
    with pytest.raises(ValueError):
        UserAuth.set_password("amy", "123")
    UserAuth.set_password("amy", "1234")
    assert UserAuth.has_password("amy")
    assert UserAuth.verify("amy", "1234")
    assert not UserAuth.verify("amy", "") and not UserAuth.verify("amy", "12345")
    assert "1234" not in open(tmp_path / "users.json").read()
    with pytest.raises(ValueError):
        UserAuth.set_password("amy", "9999")
