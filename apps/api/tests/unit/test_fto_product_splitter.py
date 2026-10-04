"""Product description splitter (ADR 0010). All texts are SYNTHETIC, written for these tests."""

from __future__ import annotations

from modules.fto.product import LONG_FEATURE_CHARS, SPLITTER_VERSION, split_description

ZH = (
    "电池包液冷板（合成示例）：\n"
    "1. 液冷板由铝合金6063挤压成型，厚度为2.5 mm。\n"
    "2、冷却液流道呈蛇形布置；流道入口与出口位于同一侧。\n"
    "（3）液冷板与电芯底面之间设置导热垫，导热系数为1.5 W/(m·K)。\n"
    "一、 电池模组通过螺栓固定在箱体上。"
)


def _texts(text: str) -> list[str]:
    return [f.text for f in split_description(text).features]


def test_chinese_numbered_list_and_clause_ends() -> None:
    assert _texts(ZH) == [
        "电池包液冷板（合成示例）：",
        "液冷板由铝合金6063挤压成型，厚度为2.5 mm。",
        "冷却液流道呈蛇形布置；",
        "流道入口与出口位于同一侧。",
        "液冷板与电芯底面之间设置导热垫，导热系数为1.5 W/(m·K)。",
        "电池模组通过螺栓固定在箱体上。",
    ]


def test_spans_point_exactly_into_the_original() -> None:
    result = split_description(ZH)
    for feature in result.features:
        (start, end), = feature.spans
        assert ZH[start:end] == feature.text
    assert [f.feature_id for f in result.features] == ["P1", "P2", "P3", "P4", "P5", "P6"]
    assert result.splitter_version == SPLITTER_VERSION


def test_english_sentences_keep_decimals_and_abbreviations() -> None:
    text = "The plate is aluminium, e.g. 6063. The channel depth is 0.8 mm. See Fig. 3 for details; the pad is 1.0 mm."
    assert _texts(text) == [
        "The plate is aluminium, e.g. 6063.",
        "The channel depth is 0.8 mm.",
        "See Fig. 3 for details;",
        "the pad is 1.0 mm.",
    ]


def test_bullets_stripped_but_signs_and_decimals_kept() -> None:
    assert _texts("- Busbar made of copper\n• Insulating film\n-5 °C minimum temperature\n2.5 mm plate") == [
        "Busbar made of copper",
        "Insulating film",
        "-5 °C minimum temperature",
        "2.5 mm plate",
    ]


def test_chinese_comma_does_not_split() -> None:
    assert _texts("导热垫设置在液冷板与电芯之间，厚度为1 mm，硬度为邵氏A 30。") == [
        "导热垫设置在液冷板与电芯之间，厚度为1 mm，硬度为邵氏A 30。"
    ]


def test_long_candidates_are_flagged_and_empty_input_reported() -> None:
    long_text = "导热垫" * (LONG_FEATURE_CHARS // 3 + 1)
    assert any("P1" in w and "split during review" in w for w in split_description(long_text).warnings)
    assert split_description("  \n ；。 ").warnings == ("no candidate features found",)
