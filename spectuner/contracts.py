from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol


@dataclass(frozen=True)
class GameArtifact:
    path: Path
    sha256: str
    build_id: str


@dataclass(frozen=True)
class Finding:
    summary: str
    evidence_ids: tuple[str, ...]
    confidence: Literal["observed", "inferred"]


@dataclass(frozen=True)
class OptimizationProposal:
    proposal_id: str
    baseline: GameArtifact
    change_sha256: str
    summary: str
    evidence_ids: tuple[str, ...]
    risks: tuple[str, ...]
    validation_steps: tuple[str, ...]


@dataclass(frozen=True)
class Approval:
    proposal_id: str
    baseline_sha256: str
    change_sha256: str
    reviewer: str
    decided_at: datetime
    decision: Literal["approved", "rejected"]


@dataclass(frozen=True)
class RollbackReceipt:
    proposal_id: str
    baseline_sha256: str
    applied_sha256: str
    restore_point: str


class GameInspector(Protocol):
    def inspect(self, artifact: GameArtifact) -> tuple[Finding, ...]: ...


class OptimizationPlanner(Protocol):
    def propose(self, artifact: GameArtifact, findings: tuple[Finding, ...]) -> tuple[OptimizationProposal, ...]: ...


class ApprovalSource(Protocol):
    def decide(self, proposal: OptimizationProposal) -> Approval: ...


class ChangeExecutor(Protocol):
    def apply(self, proposal: OptimizationProposal, approval: Approval) -> RollbackReceipt: ...

    def rollback(self, receipt: RollbackReceipt) -> GameArtifact: ...
