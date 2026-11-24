"""Best-effort QGIS project and canvas observations for a baseline session.

QGIS imports stay inside the connection function so the plugin can load
without a desktop host.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

from experiment_plugin import session as baseline

MAX_EVENTS = 2000


class HostHooks:
    """Own and gate the host callbacks connected for one session."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._enabled = True
        self._closed = False
        self._connections: list[tuple[object, str, Callable[..., None]]] = []

    def connect(self, owner: object, signal_name: str, callback: Callable[..., None]) -> None:
        def guarded(*args: object) -> None:
            with self._lock:
                if self._enabled:
                    callback(*args)

        with self._lock:
            if self._closed:
                raise RuntimeError("host hooks are closed")
            signal = getattr(owner, signal_name)
            # Track before connect: a host can attach a callback and then raise.
            self._connections.append((owner, signal_name, guarded))
            signal.connect(guarded)

    def pause(self) -> None:
        """Wait for in-flight observations and stop accepting new ones."""
        with self._lock:
            self._enabled = False

    def resume(self) -> None:
        """Resume observation after a failed attempt to finish the session."""
        with self._lock:
            if not self._closed:
                self._enabled = True

    def close(self) -> None:
        """Disable and disconnect every callback, including partial connections."""
        with self._lock:
            self._enabled = False
            self._closed = True
            connections, self._connections = self._connections, []
        failures: list[Exception] = []
        for owner, signal_name, callback in reversed(connections):
            try:
                # Reacquire the signal: a stored PyQt bound signal may crash if
                # its C++ sender has already been destroyed.
                getattr(owner, signal_name).disconnect(callback)
            except TypeError:
                # Qt reports an already-disconnected slot this way.
                pass
            except RuntimeError as exc:
                # A deleted Qt sender has already removed its connections.
                if "has been deleted" not in str(exc):
                    failures.append(exc)
            except Exception as exc:  # keep releasing the remaining connections
                failures.append(exc)
        if failures:
            raise ExceptionGroup("host hook disconnection failed", failures)


def _log_capped(
    session: baseline.HumanBaselineSession, event: str, tool: str, **fields: object
) -> None:
    """Log HOST event unless the per-session event cap is reached."""
    if session.tracker.event_count < MAX_EVENTS:
        session.log(event, tool=tool, **fields)  # type: ignore[arg-type]


def _wire_project_hooks(
    session: baseline.HumanBaselineSession, project: object, connections: HostHooks | None = None
) -> list[str]:
    """Wire project hooks. Returns a list of non-fatal warnings (empty if all wired)."""
    connections = connections if connections is not None else HostHooks()
    warnings: list[str] = []

    def layers_added(layers: object, *_args: object) -> None:
        count = len(layers or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_added", "host:project", count=count)

    def layers_removed(ids: object, *_args: object) -> None:
        count = len(ids or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_removed", "host:project", count=count)

    def crs_changed(*_args: object) -> None:
        crs = project.crs().authid()  # type: ignore[attr-defined]
        _log_capped(session, "crs_changed", "host:project", crs=crs)

    def project_read(*_args: object) -> None:
        path = project.fileName()  # type: ignore[attr-defined]
        _log_capped(session, "project_read", "host:project", path=path)

    # QGIS 4 renamed the project-read signal: projectRead -> readProject
    # (PyQt bound signal in both). Bind whichever exists so QGIS 3 and 4 hosts
    # both report hooks connected instead of silently failing the whole hook.
    def _connectable(name: str) -> object | None:
        candidate = getattr(project, name, None)
        if callable(candidate) and hasattr(candidate, "connect"):
            return candidate
        return None

    read_signal = next(
        (name for name in ("readProject", "projectRead") if _connectable(name)), None
    )

    connections.connect(project, "layersAdded", layers_added)
    connections.connect(project, "layersWillBeRemoved", layers_removed)
    connections.connect(project, "crsChanged", crs_changed)
    if read_signal is not None:
        connections.connect(project, read_signal, project_read)
    else:
        warnings.append("project_read: no project-read signal found (readProject/projectRead)")
    return warnings


def _wire_canvas_hooks(
    session: baseline.HumanBaselineSession, canvas: object, connections: HostHooks | None = None
) -> None:
    connections = connections if connections is not None else HostHooks()

    def extents_changed(*_args: object) -> None:
        extent = canvas.extent()  # type: ignore[attr-defined]
        _log_capped(
            session,
            "canvas_extent",
            "host:canvas",
            extent={
                "xmin": extent.xMinimum(),
                "ymin": extent.yMinimum(),
                "xmax": extent.xMaximum(),
                "ymax": extent.yMaximum(),
            },
        )

    def scale_changed(scale: float, *_args: object) -> None:
        _log_capped(session, "canvas_scale", "host:canvas", scale=scale)

    connections.connect(canvas, "extentsChanged", extents_changed)
    connections.connect(canvas, "scaleChanged", scale_changed)


def connect_host_hooks(
    session: baseline.HumanBaselineSession, connections: HostHooks | None = None
) -> tuple[list[str], list[str]]:
    """Best-effort QGIS host hooks. Returns (connected, failures) — never silent."""
    connections = connections if connections is not None else HostHooks()
    connected: list[str] = []
    failures: list[str] = []
    try:
        from qgis.core import QgsProject

        warnings = _wire_project_hooks(session, QgsProject.instance(), connections)
        connected.extend(["project"] if not warnings else ["project (partial)"])
        failures.extend(warnings)
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"project: {exc}")
    try:
        from qgis.utils import iface

        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is not None:
            _wire_canvas_hooks(session, canvas, connections)
            connected.append("canvas")
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"canvas: {exc}")
    return connected, failures
