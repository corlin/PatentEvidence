from uuid import UUID, uuid4
import pytest
from fastapi import HTTPException

from patent_evidence_api.core.http import parse_uuid_or_404, parse_uuids_or_404


def test_parse_uuid_or_404_valid():
    u = uuid4()
    assert parse_uuid_or_404(str(u)) == u


def test_parse_uuid_or_404_invalid():
    with pytest.raises(HTTPException) as exc_info:
        parse_uuid_or_404("not-a-uuid")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "not_found"


def test_parse_uuids_or_404_all_valid():
    u1, u2, u3 = uuid4(), uuid4(), uuid4()
    parsed = parse_uuids_or_404(str(u1), str(u2), str(u3))
    assert parsed == (u1, u2, u3)


def test_parse_uuids_or_404_one_invalid():
    u1 = uuid4()
    with pytest.raises(HTTPException) as exc_info:
        parse_uuids_or_404(str(u1), "invalid-uuid")
    assert exc_info.value.status_code == 404
