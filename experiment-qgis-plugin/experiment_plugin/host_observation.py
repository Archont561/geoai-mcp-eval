"""Best-effort QGIS project and canvas observations for a baseline session.

QGIS imports stay inside the connection function so the plugin can load
without a desktop host.
"""

from __future__ import annotations

from experiment_plugin import session as baseline

MAX_EVENTS = 2000


def _log_capped(
    session: baseline.HumanBaselineSession, event: str, tool: str, **fields: object
) -> None:
    """Log HOST event unless the per-session event cap is reached."""
    if session.tracker.event_count < MAX_EVENTS:
        session.log(event, tool=tool, **fields)  # type: ignore[arg-type]


def _wire_project_hooks(session: baseline.HumanBaselineSession, project: object) -> list[str]:
    """Wire project hooks. Returns a list of non-fatal warnings (empty if all wired)."""
    warnings: list[str] = []

    def layers_added(layers: object) -> None:
        count = len(layers or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_added", "host:project", count=count)

    def layers_removed(ids: object) -> None:
        count = len(ids or [])  # type: ignore[arg-type]
        _log_capped(session, "layers_removed", "host:project", count=count)

    def crs_changed() -> None:
        crs = project.crs().authid()  # type: ignore[attr-defined]
        _log_capped(session, "crs_changed", "host:project", crs=crs)

    def project_read() -> None:
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
        (_connectable(name) for name in ("readProject", "projectRead") if _connectable(name)),
        None,
    )

    project.layersAdded.connect(layers_added)  # type: ignore[attr-defined]
    project.layersWillBeRemoved.connect(layers_removed)  # type: ignore[attr-defined]
    project.crsChanged.connect(crs_changed)  # type: ignore[attr-defined]
    if read_signal is not None:
        read_signal.connect(project_read)
    else:
        warnings.append("project_read: no project-read signal found (readProject/projectRead)")
    return warnings


def _wire_canvas_hooks(session: baseline.HumanBaselineSession, canvas: object) -> None:
    def extents_changed() -> None:
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

    def scale_changed(scale: float) -> None:
        _log_capped(session, "canvas_scale", "host:canvas", scale=scale)

    canvas.extentsChanged.connect(extents_changed)  # type: ignore[attr-defined]
    canvas.scaleChanged.connect(scale_changed)  # type: ignore[attr-defined]


def connect_host_hooks(session: baseline.HumanBaselineSession) -> tuple[list[str], list[str]]:
    """Best-effort QGIS host hooks. Returns (connected, failures) — never silent."""
    connected: list[str] = []
    failures: list[str] = []
    try:
        from qgis.core import QgsProject

        warnings = _wire_project_hooks(session, QgsProject.instance())
        connected.extend(["project"] if not warnings else ["project (partial)"])
        failures.extend(warnings)
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"project: {exc}")
    try:
        from qgis.utils import iface

        canvas = iface.mapCanvas() if iface is not None else None
        if canvas is not None:
            _wire_canvas_hooks(session, canvas)
            connected.append("canvas")
    except Exception as exc:  # host hooks are best-effort; report instead of crashing
        failures.append(f"canvas: {exc}")
    return connected, failures
