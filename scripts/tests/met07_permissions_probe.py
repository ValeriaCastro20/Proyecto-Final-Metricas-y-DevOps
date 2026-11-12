"""Linux-only, isolated cross-user filesystem fixture. Never launches services or network."""
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import met07 as m


def child(uid, gid, action):
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read)
        try:
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
            action()
            value = {"passed": True}
        except BaseException as error:
            value = {"passed": False, "error": type(error).__name__}
        os.write(write, json.dumps(value).encode())
        os.close(write)
        os._exit(0)
    os.close(write)
    data = b""
    while True:
        part = os.read(read, 4096)
        if not part:
            break
        data += part
    os.close(read)
    os.waitpid(pid, 0)
    m.require(json.loads(data).get("passed"), "Cross-user fixture child failed")


def main():
    m.require(os.geteuid() == 0, "Permission fixture requires isolated root test process")
    with tempfile.TemporaryDirectory(prefix="met07-permissions-") as temp:
        root = Path(temp)
        # Traversable fixture parent; the IPC directory and every control file remain private.
        root.chmod(0o711)
        directory = root / "ipc"
        directory.mkdir(mode=0o700)
        os.chown(directory, 65534, 65534)
        first = lambda: m.atomic_file(directory / "state.json", {"identity": m.actor_identity()})
        child(65534, 65534, first)
        def guard():
            state = m.read_private(directory / "state.json", m.actor_identity())
            m.require(state["identity"] == m.actor_identity(), "Identity mismatch")
            m.atomic_file(directory / "ack.json", {"ok": True})
        child(65534, 65534, guard)
        def heartbeat():
            m.require(m.read_private(directory / "ack.json", m.actor_identity())["ok"], "ACK inaccessible")
            m.atomic_file(directory / "heartbeat.json", {"ok": True})
        child(65534, 65534, heartbeat)
        def result():
            m.read_private(directory / "heartbeat.json", m.actor_identity())
            m.atomic_file(directory / "result.json", {"restored": True})
        child(65534, 65534, result)
        child(65534, 65534, lambda: m.read_private(directory / "result.json", m.actor_identity()))
        def other():
            for path, mode in ((directory / "ack.json", "r"), (directory / "heartbeat.json", "w")):
                try:
                    with open(path, mode):
                        pass
                except PermissionError:
                    continue
                raise RuntimeError("Another user accessed private IPC")
        child(65533, 65533, other)
        for file in directory.iterdir():
            m.require((file.stat().st_uid, file.stat().st_gid, file.stat().st_mode & 0o777) ==
                      (65534, 65534, 0o600), "Non-private IPC file")
        # Even root's ability to bypass DAC must not bypass our identity policy.
        try:
            m.read_private(directory / "ack.json", m.actor_identity())
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Root identity fallback accepted another owner's file")
        (directory / "ack.json").chmod(0o640)
        def wrong_mode():
            try:
                m.read_private(directory / "ack.json", m.actor_identity())
            except RuntimeError:
                return
            raise RuntimeError("Relaxed file mode accepted")
        child(65534, 65534, wrong_mode)
        (directory / "ack.json").chmod(0o600)
        os.chown(directory / "ack.json", 65534, 65533)
        child(65534, 65534, wrong_mode)
        os.chown(directory / "ack.json", 65533, 65533)
        child(65534, 65534, wrong_mode)
        m.require(root.resolve().parent == Path(tempfile.gettempdir()).resolve(), "Unexpected cleanup target")
    print(json.dumps({"material": "ISOLATED_PERMISSION_FIXTURE", "passed": True, "users": 2,
                      "watchdog_executed": False, "network_executed": False}))


if __name__ == "__main__":
    main()
