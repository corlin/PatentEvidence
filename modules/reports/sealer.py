from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SealedEvidencePayload:
    case: dict[str, Any]
    document: dict[str, Any]
    features: dict[str, Any]
    search: dict[str, Any]
    candidates: list[dict[str, Any]]
    comparison: dict[str, Any]
    assessment: dict[str, Any]
    sealed_at: str
    sealed_by: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceSealer:
    """Collects all frozen lifecycle data and computes deterministic Root SHA-256."""

    def seal(
        self,
        case_data: dict[str, Any],
        doc_data: dict[str, Any],
        features_data: dict[str, Any],
        search_data: dict[str, Any],
        candidates_data: list[dict[str, Any]],
        comparison_data: dict[str, Any],
        sealed_at_iso: str,
        sealed_by_email: str,
        assessment_data: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        payload_obj = SealedEvidencePayload(
            case={
                "id": str(case_data.get("id")),
                "case_number": case_data.get("case_number"),
                "title": case_data.get("title"),
                "technical_field": case_data.get("technical_field"),
            },
            document={
                "id": str(doc_data.get("id")),
                "version_number": doc_data.get("version_number"),
                "filename": doc_data.get("filename"),
                "file_sha256": doc_data.get("file_sha256"),
            },
            features={
                "version_id": str(features_data.get("version_id")),
                "items": features_data.get("items", []),
            },
            search={
                "strategy_id": str(search_data.get("strategy_id")),
                "keywords_matrix": search_data.get("keywords_matrix", {}),
                "ipc_classes": search_data.get("ipc_classes", []),
                "boolean_query_cnipr": search_data.get("boolean_query_cnipr", ""),
            },
            candidates=candidates_data,
            comparison={
                "matrix_id": str(comparison_data.get("matrix_id")),
                "risk_level": comparison_data.get("risk_level", ""),
                "summary": comparison_data.get("summary", ""),
                "comparisons": comparison_data.get("comparisons", []),
            },
            # Sealed alongside the evidence so the root hash binds the assessment
            # facts that gate section 5. An older snapshot without this block
            # simply has no version, and the gate then refuses to publish.
            assessment={
                "has_version": bool((assessment_data or {}).get("has_version")),
                "version_number": (assessment_data or {}).get("version_number"),
                "status": (assessment_data or {}).get("status"),
                "blockers": list((assessment_data or {}).get("blockers") or []),
                "flags": list((assessment_data or {}).get("flags") or []),
                "payload_sha256": (assessment_data or {}).get("payload_sha256"),
                "rules_version": (assessment_data or {}).get("rules_version"),
                "prompt_versions": (assessment_data or {}).get("prompt_versions") or {},
                "created_at": (assessment_data or {}).get("created_at"),
                # 整个评估包一并封存：报告第 5 节渲染的每个字段都被根哈希绑住。
                "payload": (assessment_data or {}).get("payload") or {},
            },
            sealed_at=sealed_at_iso,
            sealed_by=sealed_by_email,
        )

        dict_data = payload_obj.to_dict()
        # Canonical JSON string with sorted keys
        canonical_str = json.dumps(dict_data, sort_keys=True, ensure_ascii=False)
        root_sha256 = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

        return dict_data, root_sha256
