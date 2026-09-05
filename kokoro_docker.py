#!/usr/bin/env python3
"""Bring Kokoro up before a build needs it, launching Docker Desktop if it is closed."""

import os
import subprocess
import threading
import time
from pathlib import Path
from urllib import request as urlrequest

CONTAINER = "kokoro-ui"
IMAGE = "sensejworld/kokorotts:latest"
PORT = 7860
PING = f"http://localhost:{PORT}/tts/ping"
DESKTOP = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
RUN_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "run"

# Only one attempt at a time. Two overlapping launches of Docker Desktop
# race each other and can leave a socket behind in RUN_DIR that Docker then
# refuses to start on top of.
_gate = threading.Lock()


def api_alive(timeout=3):
    try:
        with urlrequest.urlopen(PING, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _docker(*args, timeout=25):
    try:
        return subprocess.run(("docker",) + args, capture_output=True,
                              text=True, timeout=timeout)
    except Exception:
        return None


def docker_alive():
    result = _docker("info", "--format", "{{.ServerVersion}}", timeout=20)
    return bool(result and result.returncode == 0)


def container_state():
    result = _docker("inspect", "-f", "{{.State.Status}}", CONTAINER, timeout=20)
    if not result or result.returncode != 0:
        return "missing"
    return result.stdout.strip() or "missing"


def status():
    """Cheap enough to call on every page load."""
    if api_alive():
        return {"api": True, "docker": True, "container": "running"}
    docker = docker_alive()
    return {"api": False, "docker": docker,
            "container": container_state() if docker else "unknown"}


def clear_stale_sockets():
    """Move aside socket folders a previous Docker left behind.

    Docker Desktop 4.80 fails to start with "remove <socket>: The file cannot
    be accessed by the system" and quits. The sockets are AF_UNIX reparse
    points that cannot be deleted by anything - plain unlink, and CreateFileW
    with FILE_FLAG_OPEN_REPARSE_POINT, both fail with WinError 1920 even with
    no Docker process running. Renaming the containing folder does work, and
    Docker recreates it clean on the next start.
    """
    if os.name != "nt":
        return []
    if docker_processes_running():
        return []                     # never touch these while Docker is alive
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved = []
    for folder in (local / "Docker" / "run", local / "docker-secrets-engine"):
        if not folder.is_dir() or not _has_stuck_socket(folder):
            continue
        try:
            folder.rename(folder.with_name(f"{folder.name}.stale-{stamp}"))
            moved.append(folder.name)
        except OSError:
            pass
    return moved


def _has_stuck_socket(folder):
    """A socket here that cannot even be opened is what stops Docker starting."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    for entry in entries:
        try:
            entry.stat()
        except OSError:
            return True               # WinError 1920 - the stuck kind
    return False


def docker_processes_running():
    result = subprocess.run(["tasklist", "/NH"], capture_output=True, text=True)
    if result.returncode != 0:
        return True                   # cannot tell, so assume yes and do nothing
    lowered = result.stdout.lower()
    return ("docker desktop.exe" in lowered
            or "com.docker.backend.exe" in lowered)


def desktop_running():
    """Is the Docker Desktop app itself up, whatever the engine is doing?"""
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Docker Desktop.exe", "/NH"],
        capture_output=True, text=True)
    return bool(result.returncode == 0 and "Docker Desktop.exe" in result.stdout)


def desktop_stalled(seconds):
    """Explain a start that never produced a working engine."""
    if desktop_running():
        return (f"Docker Desktop is running but its engine did not come up within "
                f"{seconds}s. Check its window: it often shows an error there. A "
                f"common one after an unclean shutdown is a leftover socket in "
                f"{RUN_DIR}, which Docker cannot delete on the next start - "
                f"quitting Docker Desktop fully and reopening it clears that.")
    return (f"Docker Desktop did not finish starting within {seconds}s, and its "
            "process is no longer running, so it likely failed or was closed.")


def ensure(log=print, wait_docker=180, wait_api=120, may_start_desktop=True):
    """Return {ok, action} or {ok: False, error}. Safe to call when already up.

    may_start_desktop=False will start a stopped container but never launch
    Docker Desktop itself, which is what the server does on startup: a restart
    should not drag a closed Docker back up behind the user.
    """
    if api_alive():
        return {"ok": True, "action": "already running"}
    if not _gate.acquire(blocking=False):
        return {"ok": False, "error": "Kokoro is already being started."}
    try:
        return _ensure(log, wait_docker, wait_api, may_start_desktop)
    finally:
        _gate.release()


def _ensure(log, wait_docker, wait_api, may_start_desktop):
    done = []
    if not docker_alive():
        if not may_start_desktop:
            return {"ok": False, "error": "Docker is not running."}
        if not DESKTOP.exists():
            return {"ok": False,
                    "error": "Docker is not running, and Docker Desktop was not found at "
                             f"{DESKTOP}. Start Docker yourself, then try again."}
        cleared = clear_stale_sockets()
        if cleared:
            log("moved aside stale socket folders Docker could not delete: "
                + ", ".join(cleared))
        log("Docker is not running. Starting Docker Desktop, this takes a moment")
        try:
            # Fully detached. As a child of this server it can be dragged down
            # when the server is killed, and a half-started Docker leaves
            # sockets behind in Local/Docker/run that make the next start fail.
            flags = 0
            if os.name == "nt":
                flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            subprocess.Popen([str(DESKTOP)], close_fds=True, creationflags=flags,
                             cwd=str(DESKTOP.parent))
        except Exception as exc:
            return {"ok": False, "error": f"Could not launch Docker Desktop: {exc}"}
        deadline = time.time() + wait_docker
        while time.time() < deadline:
            if docker_alive():
                break
            time.sleep(3)
        else:
            return {"ok": False, "error": desktop_stalled(wait_docker)}
        done.append("started Docker Desktop")
        log("Docker is up")

    state = container_state()
    if state == "missing":
        log(f"No {CONTAINER} container yet, creating it")
        # Long timeout: this pulls the image the first time.
        result = _docker("run", "-d", "--name", CONTAINER,
                         "-p", f"{PORT}:{PORT}", IMAGE, timeout=900)
        if not result or result.returncode != 0:
            return {"ok": False, "error": "docker run failed: " +
                    (result.stderr.strip() if result else "no response from docker")}
        done.append("created the container")
    elif state != "running":
        log(f"Starting the {CONTAINER} container")
        result = _docker("start", CONTAINER, timeout=90)
        if not result or result.returncode != 0:
            return {"ok": False, "error": "docker start failed: " +
                    (result.stderr.strip() if result else "no response from docker")}
        done.append("started the container")

    log("Waiting for Kokoro to answer")
    deadline = time.time() + wait_api
    while time.time() < deadline:
        if api_alive():
            log("Kokoro is ready")
            return {"ok": True, "action": ", ".join(done) or "already running"}
        time.sleep(2)
    return {"ok": False,
            "error": f"The container is up but Kokoro did not answer within {wait_api}s."}


if __name__ == "__main__":
    print(ensure())
