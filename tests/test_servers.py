"""Tests for the SSH server registry, manager actions, and agent tools."""
from __future__ import annotations

import json

import pytest

from alterego_training_hub.servers import (
    ServerEntry,
    ServerError,
    ServerManager,
    ServerStore,
)


class FakeSecrets:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def get(self, key):
        if key not in self.data:
            raise RuntimeError("нет ключа")
        return self.data[key]

    def delete(self, key):
        self.data.pop(key, None)


class FakeRunner:
    def __init__(self, entry, secret, *, output="ok", exit_code=0, fail_connect=False):
        self.entry = entry
        self.secret = secret
        self.output = output
        self.exit_code = exit_code
        self.fail_connect = fail_connect
        self.commands = []
        self.connected = False
        self.closed = False

    def connect(self):
        if self.fail_connect:
            raise ServerError("нет связи")
        self.connected = True

    def run(self, command, timeout=60.0):
        self.commands.append((command, timeout))
        return {"ok": self.exit_code == 0, "exit_code": self.exit_code,
                "command": command, "output": self.output}

    def close(self):
        self.closed = True


@pytest.fixture()
def store(tmp_path):
    return ServerStore(tmp_path / "servers.json")


def make_entry(**overrides):
    entry = ServerEntry(name="gpu-box", host="10.0.0.5", user="dev",
                        auth_kind="key")
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def test_store_roundtrip_validation_and_no_secrets(store):
    entry = make_entry()
    store.save(entry)
    loaded = store.list()
    assert len(loaded) == 1
    assert loaded[0].name == "gpu-box"
    assert loaded[0].address == "dev@10.0.0.5:22"
    assert store.find("gpu-box").id == entry.id
    assert store.find(entry.id).host == "10.0.0.5"

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert "password" not in json.dumps(raw)
    assert raw[0]["host"] == "10.0.0.5"

    store.delete(entry.id)
    assert store.list() == []

    bad = make_entry(name="", host="h")
    with pytest.raises(ServerError):
        store.save(bad)
    with pytest.raises(ServerError):
        make_entry(port=70000).validate()
    with pytest.raises(ServerError):
        make_entry(auth_kind="passwordless").validate()


def test_manager_test_info_and_run_command(store):
    secrets = FakeSecrets()
    runners = []

    def factory(entry, secret):
        runner = FakeRunner(entry, secret, output="hello\n")
        runners.append(runner)
        return runner

    manager = ServerManager(store, secrets, runner_factory=factory)
    entry = manager.save(make_entry())

    result = manager.test_connection(entry.id)
    assert result["ok"] is True
    assert result["output"] == "hello\n"
    assert runners[-1].connected and runners[-1].closed
    assert runners[-1].commands[0][0] == "echo connected && hostname"

    result = manager.info(entry.id)
    assert result["info"] == "hello\n"
    assert "nvidia-smi" in runners[-1].commands[0][0]

    result = manager.run_command(entry.id, "python train.py")
    assert result["command"] == "python train.py"
    assert result["server"] == "gpu-box"

    with pytest.raises(ServerError):
        manager.run_command(entry.id, "   ")
    with pytest.raises(ServerError):
        manager.run_command("missing", "ls")


def test_manager_password_auth_requires_saved_secret(store):
    secrets = FakeSecrets()
    seen = {}

    def factory(entry, secret):
        seen["secret"] = secret
        return FakeRunner(entry, secret)

    manager = ServerManager(store, secrets, runner_factory=factory)
    entry = manager.save(make_entry(auth_kind="password"))

    with pytest.raises(ServerError):
        manager.test_connection(entry.id)  # password not saved yet

    manager.set_password(entry.id, "s3cret")
    assert manager.has_password(entry.id) is True
    assert secrets.data[manager.secret_key(entry.id)] == "s3cret"
    manager.test_connection(entry.id)
    assert seen["secret"] == "s3cret"

    manager.delete(entry.id)
    assert manager.secret_key(entry.id) not in secrets.data
    assert store.list() == []


def test_connection_failure_is_reported(store):
    def factory(entry, secret):
        return FakeRunner(entry, secret, fail_connect=True)

    manager = ServerManager(store, FakeSecrets(), runner_factory=factory)
    entry = manager.save(make_entry())
    with pytest.raises(ServerError):
        manager.test_connection(entry.id)


def test_agent_tools_bridge(store):
    def factory(entry, secret):
        return FakeRunner(entry, secret, output="out")

    manager = ServerManager(store, FakeSecrets(), runner_factory=factory)
    manager.save(make_entry())
    handlers, schemas, mutations = manager.agent_tools()

    assert set(handlers) == {"list_servers", "server_info", "run_on_server"}
    assert {item["function"]["name"] for item in schemas} == set(handlers)
    assert mutations == frozenset({"run_on_server"})

    listed = handlers["list_servers"]({})
    assert listed["ok"] and listed["servers"][0]["name"] == "gpu-box"
    assert handlers["server_info"]({"server": "gpu-box"})["ok"] is True
    result = handlers["run_on_server"]({"server": "gpu-box", "command": "ls"})
    assert result["ok"] is True and result["output"] == "out"
    assert handlers["run_on_server"]({"server": "nope", "command": "ls"})["ok"] is False


def test_ssh_host_keys_are_pinned_on_first_use(tmp_path, monkeypatch):
    """Unknown host keys are saved to app known_hosts; saved keys are loaded."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    import sys
    import types

    from alterego_training_hub.servers import SshRunner, known_hosts_path

    calls = {}

    class FakeKey:
        def get_name(self):
            return "ssh-ed25519"

        def get_base64(self):
            return "AAAA"

        def asbytes(self):
            return b"\x00\x01\x02"

    class FakeMissingHostKeyPolicy:
        pass

    class FakeHostKeys:
        def add(self, hostname, name, key):
            calls.setdefault("added", []).append(hostname)

    class FakeClient:
        def load_system_host_keys(self):
            calls["system_keys"] = True

        def load_host_keys(self, path):
            calls.setdefault("loaded", []).append(path)

        def set_missing_host_key_policy(self, policy):
            calls["policy"] = policy

        def get_host_keys(self):
            return FakeHostKeys()

        def connect(self, **kwargs):
            calls["connect"] = kwargs
            transport = types.SimpleNamespace(
                get_remote_server_key=lambda: FakeKey())
            self._transport = transport

        def get_transport(self):
            return self._transport

        def exec_command(self, command, timeout=60.0):
            raise AssertionError("не должен вызываться в этом тесте")

        def close(self):
            pass

    fake_paramiko = types.ModuleType("paramiko")
    fake_paramiko.SSHClient = FakeClient
    fake_paramiko.MissingHostKeyPolicy = FakeMissingHostKeyPolicy
    fake_paramiko.AuthenticationException = type(
        "AuthenticationException", (Exception,), {})
    fake_paramiko.BadHostKeyException = type("BadHostKeyException", (Exception,), {})
    fake_paramiko.SSHException = type("SSHException", (Exception,), {})
    monkeypatch.setitem(sys.modules, "paramiko", fake_paramiko)

    runner = SshRunner("10.0.0.5", 22, "dev", password="pw")
    runner.connect()
    assert calls["system_keys"] is True
    assert isinstance(calls["policy"], FakeMissingHostKeyPolicy)

    # First contact: the policy pins the key to the app known_hosts file.
    pin_file = known_hosts_path()
    calls["policy"].missing_host_key(
        FakeClient(), "[10.0.0.5]:22", FakeKey())
    content = pin_file.read_text(encoding="utf-8")
    assert "[10.0.0.5]:22 ssh-ed25519 AAAA" in content

    # Fingerprint is computed after connect.
    assert runner.host_fingerprint.startswith("SHA256:")

    # A second runner loads the pinned file.
    runner2 = SshRunner("10.0.0.5", 22, "dev")
    runner2.connect()
    assert any(str(pin_file) == p for p in calls.get("loaded", []))
