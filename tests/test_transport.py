"""Smoke tests for SSH transport.

Real SSH round-trip testing requires a running sshd. This container doesn't
ship one, so we only verify construction + graceful failure. The real
end-to-end test happens when this code runs on Mac Studio against the home
server (192.168.5.101).
"""
import pytest

from memloom.config import HostConfig
from memloom.transport import LocalTransport, SSHTransport, make_transport


def test_local_transport_construction():
    t = LocalTransport(root="/tmp")
    assert t.name == "local"


def test_ssh_transport_construction():
    """Verify SSHTransport can be constructed from config (no network call)."""
    t = SSHTransport(
        host="192.168.5.101",
        user="beta",
        key_file="/home/node/.ssh/id_ed25519",
        port=22,
    )
    assert t.name == "ssh"
    assert t._host == "192.168.5.101"


def test_make_transport_routes_correctly():
    local = make_transport(HostConfig(name="local", transport="local"))
    assert isinstance(local, LocalTransport)

    ssh = make_transport(HostConfig(
        name="home",
        transport="ssh",
        ssh_host="192.168.5.101",
        ssh_user="beta",
        ssh_key_file="/home/node/.ssh/id_ed25519",
    ))
    assert isinstance(ssh, SSHTransport)


def test_make_transport_ssh_requires_host_user():
    with pytest.raises(ValueError, match="ssh_host/ssh_user"):
        make_transport(HostConfig(name="home", transport="ssh"))


def test_ssh_transport_handles_unreachable_gracefully():
    """Attempting to connect to an unreachable host should raise, not hang."""
    t = SSHTransport(
        host="127.0.0.1",  # no sshd on this container
        user="nobody",
        key_file="/home/node/.ssh/id_ed25519",
        port=22,
        connect_timeout=2,
    )
    with pytest.raises(Exception):
        # _run() will fail because there's no sshd at 127.0.0.1:22
        t._run("true", warn_only=False)
