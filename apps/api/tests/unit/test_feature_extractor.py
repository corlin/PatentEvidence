from __future__ import annotations

from modules.features.extractor import RuleFeatureExtractor


def test_rule_feature_extractor_with_sections() -> None:
    extractor = RuleFeatureExtractor()
    paragraphs = [
        {
            "id": "p1",
            "index": 1,
            "section": "技术领域",
            "text": "本申请涉及一种基于混合精度量化的大语言模型推理方法与系统。",
            "offset_start": 0,
            "offset_end": 32,
        },
        {
            "id": "p2",
            "index": 2,
            "section": "发明内容",
            "text": "本发明的技术方案包括：通过获取预训练权重矩阵并进行奇异值分解；基于敏感度指标对注意力头进行动态位宽分配；构建非对称量化查找表以执行低延迟推理。",
            "offset_start": 33,
            "offset_end": 105,
        },
        {
            "id": "p3",
            "index": 3,
            "section": "具体实施方式",
            "text": "在具体实施中，所述动态位宽分配步骤还包括：根据反向传播梯度方差设定 2-bit 至 8-bit 的量化阈值。",
            "offset_start": 106,
            "offset_end": 160,
        },
    ]

    features = extractor.extract(paragraphs)

    assert len(features) >= 3
    # Check preamble
    assert features[0].feature_type == "preamble"
    assert features[0].source_paragraph_id == "p1"
    assert "推理方法" in features[0].feature_statement

    # Check characterizing
    assert any(f.feature_type == "characterizing" for f in features)
    assert any("奇异值分解" in f.feature_statement for f in features)
    assert any(f.source_paragraph_id == "p2" for f in features)


def test_rule_feature_extractor_fallback() -> None:
    extractor = RuleFeatureExtractor()
    paragraphs = [
        {
            "id": "p1",
            "index": 1,
            "section": "正文",
            "text": "简易测试交底书正文第一段，包含基础特征说明。",
            "offset_start": 0,
            "offset_end": 24,
        },
        {
            "id": "p2",
            "index": 2,
            "section": "正文",
            "text": "第二段描述了通过特定传感器收集信号的技术手段。",
            "offset_start": 25,
            "offset_end": 48,
        },
    ]
    features = extractor.extract(paragraphs)
    assert len(features) >= 1
    assert features[0].source_paragraph_id == "p1"
