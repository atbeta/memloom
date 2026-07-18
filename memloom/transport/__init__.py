"""Transport package: how to reach files on a host."""
from .base import FileStat, Transport, normalize_path
from .local import LocalTransport
from .ssh import SSHTransport


def make_transport(host_config) -> Transport:
    """Build a transport from a HostConfig (from memory_pipeline.config)."""
    if host_config.transport == "local":
        return LocalTransport()
    if host_config.transport == "ssh":
        if not (host_config.ssh_host and host_config.ssh_user):
            raise ValueError(
                f"Host '{host_config.name}' uses ssh transport but is missing "
                f"ssh_host/ssh_user."
            )
        return SSHTransport(
            host=host_config.ssh_host,
            user=host_config.ssh_user,
            key_file=host_config.ssh_key_file,
            port=host_config.ssh_port,
            password=host_config.ssh_password,
        )
    raise ValueError(f"Unknown transport: {host_config.transport!r}")


__all__ = ["Transport", "LocalTransport", "SSHTransport", "FileStat", "make_transport"]
