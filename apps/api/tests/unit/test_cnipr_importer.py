from __future__ import annotations

from modules.search.importer import CniprResultsImporter, normalize_pub_number


def test_normalize_pub_number() -> None:
    assert normalize_pub_number("cn 118000123 a") == "CN118000123A"
    assert normalize_pub_number("US-2023/0385619-A1") == "US20230385619A1"
    assert normalize_pub_number("EP.4283910.A1") == "EP4283910A1"


def test_cnipr_importer_csv() -> None:
    importer = CniprResultsImporter()
    csv_data = """公开号,发明名称,摘要,公开日,申请人,IPC分类号
CN117283912A,大模型量化系统,本发明通过矩阵分解实现低位宽量化,2024-03-15,前沿科技公司,G06N 3/08
CN116549201B,稀疏查找表方法,本发明提出一种非对称查找表结构,2023-11-20,先进计算公司,G06F 17/16
"""
    results = importer.import_from_csv(csv_data)
    assert len(results) == 2
    assert results[0].publication_number_normalized == "CN117283912A"
    assert results[0].title == "大模型量化系统"
    assert results[0].ipc_classification == "G06N 3/08"
    assert results[1].publication_number_normalized == "CN116549201B"


def test_cnipr_importer_plain_text() -> None:
    importer = CniprResultsImporter()
    text_data = """CN118999001A
CN118999002A
"""
    results = importer.import_from_text(text_data)
    assert len(results) == 2
    assert results[0].publication_number_normalized == "CN118999001A"
    assert results[1].publication_number_normalized == "CN118999002A"
