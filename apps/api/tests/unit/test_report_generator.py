from __future__ import annotations

from modules.reports.generator import MarkdownReportGenerator
from modules.reports.sealer import EvidenceSealer


def test_evidence_sealer_computes_deterministic_sha256() -> None:
    sealer = EvidenceSealer()
    case_data = {
        "id": "c-1",
        "case_number": "2026-TEST-001",
        "title": "大模型量化系统",
        "technical_field": "AI",
    }
    doc_data = {
        "id": "d-1",
        "version_number": 1,
        "filename": "disclosure.docx",
        "file_sha256": "abcdef123456",
    }
    features_data = {
        "version_id": "fv-1",
        "items": [
            {
                "feature_code": "F1",
                "feature_type": "preamble",
                "feature_statement": "大模型推理方法",
                "source_paragraph_id": "p1",
            }
        ],
    }
    search_data = {
        "strategy_id": "s-1",
        "keywords_matrix": {"大模型": ["LLM"]},
        "ipc_classes": [{"code": "G06N 3/08"}],
        "boolean_query_cnipr": "(大模型 OR LLM)",
    }
    candidates_data = [
        {
            "publication_number": "CN117283912A",
            "title": "大模型量化",
            "triage_status": "included",
            "exclusion_reason": None,
        }
    ]
    comparison_data = {
        "matrix_id": "m-1",
        "risk_level": "high_novelty_risk",
        "summary": "全面公开",
        "comparisons": [
            {
                "feature_code": "F1",
                "candidate_pub_number": "CN117283912A",
                "judgment": "identical",
                "citation_location": "说明书第[0025]段",
                "citation_quote": "大模型推理系统",
                "reasoning_analysis": "完全相同",
            }
        ],
    }

    payload1, hash1 = sealer.seal(
        case_data,
        doc_data,
        features_data,
        search_data,
        candidates_data,
        comparison_data,
        "2026-09-02T12:00:00Z",
        "agent@firm.com",
    )
    payload2, hash2 = sealer.seal(
        case_data,
        doc_data,
        features_data,
        search_data,
        candidates_data,
        comparison_data,
        "2026-09-02T12:00:00Z",
        "agent@firm.com",
    )

    assert hash1 == hash2
    assert len(hash1) == 64

    # Changing any field changes the root hash
    candidates_mod = [
        {
            "publication_number": "CN117283912A",
            "title": "大模型量化 (MOD)",
            "triage_status": "included",
        }
    ]
    _, hash3 = sealer.seal(
        case_data,
        doc_data,
        features_data,
        search_data,
        candidates_mod,
        comparison_data,
        "2026-09-02T12:00:00Z",
        "agent@firm.com",
    )
    assert hash3 != hash1


def test_markdown_report_generator_formatting() -> None:
    generator = MarkdownReportGenerator()
    payload = {
        "case": {
            "case_number": "2026-CASE-099",
            "title": "稀疏量化",
            "technical_field": "通信",
        },
        "document": {
            "filename": "spec.docx",
            "version_number": 1,
            "file_sha256": "12345",
        },
        "features": {
            "items": [
                {
                    "feature_code": "F1",
                    "feature_type": "preamble",
                    "source_paragraph_id": "p1",
                    "feature_statement": "特征1语句",
                }
            ]
        },
        "search": {"boolean_query_cnipr": "(量化 OR 稀疏)"},
        "candidates": [
            {
                "publication_number": "CN10001A",
                "title": "现有技术",
                "triage_status": "included",
                "exclusion_reason": None,
            }
        ],
        "comparison": {
            "risk_level": "inventiveness_risk",
            "summary": "存在结合启示",
            "comparisons": [
                {
                    "feature_code": "F1",
                    "candidate_pub_number": "CN10001A",
                    "judgment": "equivalent",
                    "citation_location": "第[0012]段",
                    "citation_quote": "引文测试",
                    "reasoning_analysis": "等同手段",
                }
            ],
        },
        "sealed_at": "2026-09-02T12:00:00Z",
        "sealed_by": "auditor@law.com",
    }
    root_hash = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

    md = generator.generate(payload, root_hash)

    assert "# 专利证据分析与法律评估报告" in md
    assert "2026-CASE-099" in md
    assert "| `F1` | 前序特征 | `p1` | 特征1语句 |" in md
    assert "(量化 OR 稀疏)" in md
    assert "🟡 等同替代" in md
    assert root_hash in md
    assert "auditor@law.com" in md
