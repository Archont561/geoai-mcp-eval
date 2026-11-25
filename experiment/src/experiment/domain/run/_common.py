"""Shared strict Pydantic configuration and typed English experiment ontology enums."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict

STRICT_MODEL = ConfigDict(extra="forbid", frozen=True)


class RunStage(StrEnum):
    """Lifecycle stage of an experiment run."""

    PREFLIGHT = "preflight"
    SMOKE = "smoke"
    PILOT = "pilot"
    STUDY = "study"


class Arm(StrEnum):
    """Automated agent study arms executed by the experiment CLI."""

    A = "A"
    B = "B"

    @classmethod
    def expand(cls, raw: str) -> tuple[Arm, ...]:
        """Parse ``both|A|B`` (case-insensitive) into an ordered tuple of arms."""
        key = raw.strip().lower()
        mapping: dict[str, tuple[Arm, ...]] = {
            "both": (cls.A, cls.B),
            "a": (cls.A,),
            "b": (cls.B,),
        }
        if key not in mapping:
            raise ValueError(f"--arm must be one of both|A|B, got {raw!r}")
        return mapping[key]

    def to_paradigm(self) -> Paradigm:
        """Return the English experimental paradigm corresponding to this arm."""
        return Paradigm.from_arm(self)


class Driver(StrEnum):
    """Cell execution driver backend."""

    SCRIPTED = "scripted"
    OLLAMA = "ollama"

    @classmethod
    def parse(cls, raw: str) -> Driver:
        """Parse a driver identifier or raise ``ValueError``."""
        try:
            return cls(raw.strip().lower())
        except ValueError as exc:
            names = ", ".join(member.value for member in cls)
            raise ValueError(f"--driver must be one of {names}") from exc

    def model_label(self, model: str) -> str:
        """Return the human-readable model label for reports and manifests."""
        return model if self is Driver.OLLAMA else "scripted-canned"


class Paradigm(StrEnum):
    """Experimental agent/human interaction paradigm."""

    TYPED_MCP = "typed_mcp"
    CODEGEN = "codegen"
    HYBRID_MCP_CODE = "hybrid_mcp_code"
    CODE_DRIVING_MCP = "code_driving_mcp"
    HUMAN_GUI = "human_gui"

    @classmethod
    def from_arm(cls, arm: str | Arm) -> Paradigm:
        """Translate a legacy arm letter (A/B/C/D/H) into its English paradigm."""
        key = str(arm).strip().upper()
        if key not in _ARM_TO_PARADIGM:
            raise ValueError(f"unknown arm {arm!r}; expected one of {sorted(_ARM_TO_PARADIGM)}")
        return _ARM_TO_PARADIGM[key]

    def allows_enforcement(self) -> bool:
        """Return True when non-``none`` boundary enforcement levels are valid."""
        return self not in (Paradigm.CODEGEN, Paradigm.HUMAN_GUI)


class EnforcementLevel(StrEnum):
    """Boundary enforcement intensity for structured-interface paradigms."""

    NONE = "none"
    DECLARATIVE = "declarative"
    SYNTACTIC = "syntactic"
    SEMANTIC_REPAIR = "semantic_repair"
    TRANSACTIONAL = "transactional"

    @classmethod
    def from_code(cls, code: str) -> EnforcementLevel:
        """Translate a legacy enforcement code (N0..N4) into its English level."""
        key = code.strip().upper()
        if key not in _ENFORCE_TO_LEVEL:
            raise ValueError(
                f"unknown enforcement code {code!r}; expected one of {sorted(_ENFORCE_TO_LEVEL)}"
            )
        return _ENFORCE_TO_LEVEL[key]

    @classmethod
    def parse(cls, raw: str) -> EnforcementLevel:
        """Parse an English enforcement level name or legacy N0..N4 code."""
        cleaned = raw.strip()
        try:
            return cls(cleaned.lower())
        except ValueError:
            return cls.from_code(cleaned)

    def legacy_code(self) -> str:
        """Return the legacy N0..N4 shorthand code for this enforcement level."""
        return _LEVEL_TO_CODE[self]


class ExecutionStatus(StrEnum):
    """Outcome status of one executed trial."""

    OK = "ok"
    ABORTED = "aborted"
    ERROR = "error"
    SMOKE = "smoke"

    @classmethod
    def parse(cls, raw: object, *, default: ExecutionStatus = OK) -> ExecutionStatus:
        """Normalize a raw status token (including ``mock-smoke``) to ``ExecutionStatus``."""
        if not isinstance(raw, str):
            return default
        cleaned = raw.strip().lower()
        if cleaned == "mock-smoke":
            return cls.SMOKE
        try:
            return cls(cleaned)
        except ValueError:
            return default


class AssertionTier(StrEnum):
    """Complexity tier of an oracle assertion."""

    TRIVIAL = "trivial"
    SPATIAL = "spatial"
    VALUE = "value"

    @classmethod
    def infer(
        cls,
        assertion_type: str,
        *,
        explicit_tier: str | None = None,
    ) -> AssertionTier | None:
        """Resolve an assertion's tier from an explicit alias/name or assertion type."""
        if explicit_tier is not None:
            mapped = _TIER_ALIASES.get(explicit_tier.strip().lower())
            if mapped is not None:
                return mapped
        return _ASSERTION_TYPE_TO_TIER.get(assertion_type.strip().lower())


class ArtifactKind(StrEnum):
    """Classification of a file stored inside a trial archive."""

    DELIVERABLE = "deliverable"
    TRANSCRIPT = "transcript"
    LOG = "log"
    ORACLE_PASSES = "oracle_passes"
    SCRIPT = "script"
    OTHER = "other"

    @classmethod
    def from_filename(cls, rel_path: str) -> ArtifactKind:
        """Classify a relative trial artifact path into an ``ArtifactKind``."""
        name = rel_path.rsplit("/", 1)[-1].lower()
        if name in _EXACT_ARTIFACT_KINDS:
            return _EXACT_ARTIFACT_KINDS[name]
        if name.startswith("oracle") and name.endswith(".json"):
            return cls.ORACLE_PASSES
        for suffix, kind in _SUFFIX_ARTIFACT_KINDS:
            if name.endswith(suffix):
                return kind
        return cls.OTHER


class TrajectoryClass(StrEnum):
    """Descriptive post-hoc coding of an agent's tool/code trajectory."""

    TYPED_ONLY = "typed_only"
    CODE_ONLY = "code_only"
    MIXED = "mixed"


class FailureClass(StrEnum):
    """Descriptive post-hoc failure taxonomy for unsuccessful trials."""

    INTERFACE_ADJACENT = "interface_adjacent"
    WORKFLOW_SILENT = "workflow_silent"
    HALLUCINATED_STRUCTURE = "hallucinated_structure"
    OTHER = "other"


_ARM_TO_PARADIGM: dict[str, Paradigm] = {
    "A": Paradigm.TYPED_MCP,
    "B": Paradigm.CODEGEN,
    "C": Paradigm.HYBRID_MCP_CODE,
    "D": Paradigm.CODE_DRIVING_MCP,
    "H": Paradigm.HUMAN_GUI,
}
_ENFORCE_TO_LEVEL: dict[str, EnforcementLevel] = {
    "N0": EnforcementLevel.NONE,
    "N1": EnforcementLevel.DECLARATIVE,
    "N2": EnforcementLevel.SYNTACTIC,
    "N3": EnforcementLevel.SEMANTIC_REPAIR,
    "N4": EnforcementLevel.TRANSACTIONAL,
}
_LEVEL_TO_CODE: dict[EnforcementLevel, str] = {
    level: code for code, level in _ENFORCE_TO_LEVEL.items()
}
_TIER_ALIASES: dict[str, AssertionTier] = {
    "a": AssertionTier.TRIVIAL,
    "b": AssertionTier.SPATIAL,
    "c": AssertionTier.VALUE,
    "trivial": AssertionTier.TRIVIAL,
    "spatial": AssertionTier.SPATIAL,
    "value": AssertionTier.VALUE,
}
_ASSERTION_TYPE_TO_TIER: dict[str, AssertionTier] = {
    "file_exists": AssertionTier.TRIVIAL,
    "ogr_readable": AssertionTier.TRIVIAL,
    "feature_count": AssertionTier.TRIVIAL,
    "geojson_feature_count": AssertionTier.TRIVIAL,
    "raster_shape": AssertionTier.TRIVIAL,
    "nodata_ok": AssertionTier.TRIVIAL,
    "fields_present": AssertionTier.TRIVIAL,
    "crs_equals": AssertionTier.SPATIAL,
    "axis_order_ok": AssertionTier.SPATIAL,
    "geom_type_in": AssertionTier.SPATIAL,
    "geometry_valid": AssertionTier.SPATIAL,
    "de9im_relation": AssertionTier.SPATIAL,
    "representative_point_matches": AssertionTier.SPATIAL,
    "extent_within_tol": AssertionTier.SPATIAL,
    "buffer_distance": AssertionTier.SPATIAL,
    "attr_stats": AssertionTier.VALUE,
    "jenks_classification": AssertionTier.VALUE,
    "min_dist_to": AssertionTier.VALUE,
}
_EXACT_ARTIFACT_KINDS: dict[str, ArtifactKind] = {
    "transcript.jsonl": ArtifactKind.TRANSCRIPT,
    "result.json": ArtifactKind.DELIVERABLE,
    "result.geojson": ArtifactKind.DELIVERABLE,
}
_SUFFIX_ARTIFACT_KINDS: tuple[tuple[str, ArtifactKind], ...] = (
    (".gpkg", ArtifactKind.DELIVERABLE),
    (".log", ArtifactKind.LOG),
    (".py", ArtifactKind.SCRIPT),
)

ENFORCEMENT_LEVELS: tuple[EnforcementLevel, ...] = tuple(EnforcementLevel)


def arm_to_paradigm(arm: str) -> Paradigm:
    """Translate a legacy arm letter (A/B/C/D/H) into its English paradigm name."""
    return Paradigm.from_arm(arm)


def enforce_code_to_level(code: str) -> EnforcementLevel:
    """Translate a legacy enforcement code (N0..N4) into its English level name."""
    return EnforcementLevel.from_code(code)


def parse_enforcement_level(raw: str) -> EnforcementLevel:
    """Parse an English enforcement level name or legacy N0..N4 code."""
    return EnforcementLevel.parse(raw)


def parse_execution_status(
    raw: object, *, default: ExecutionStatus = ExecutionStatus.OK
) -> ExecutionStatus:
    """Normalize a raw status token (including ``mock-smoke``) to :class:`ExecutionStatus`."""
    return ExecutionStatus.parse(raw, default=default)
