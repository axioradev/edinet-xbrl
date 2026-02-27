"""Unit tests for the EDINET API v2 client. All HTTP mocked with respx."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx
from conftest import (
    EMPTY_API_RESPONSE,
    SAMPLE_API_RESPONSE,
    SAMPLE_DOC_RESULT,
    SAMPLE_DOC_RESULT_NULLABLE,
    make_empty_zip,
    make_ixbrl_zip,
    make_xbrl_zip,
)

from edinet_xbrl.client import (
    DocumentListResponse,
    DocumentMetadata,
    EdinetApiError,
    EdinetClient,
)

BASE = "https://api.edinet-fsa.go.jp/api/v2"


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    def test_no_api_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EDINET_API_KEY", raising=False)
        with pytest.raises(ValueError, match="EDINET API key is required"):
            EdinetClient()

    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EDINET_API_KEY", "env-key")
        client = EdinetClient()
        assert client._api_key == "env-key"

    async def test_use_outside_context_manager_raises(self):
        client = EdinetClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="async context manager"):
            await client.list_documents(date(2024, 3, 29))


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


class TestValidators:
    def test_parse_flag_string_1(self):
        doc = DocumentMetadata.model_validate(SAMPLE_DOC_RESULT)
        assert doc.has_xbrl is True

    def test_parse_flag_string_0(self):
        doc = DocumentMetadata.model_validate(SAMPLE_DOC_RESULT_NULLABLE)
        assert doc.has_xbrl is False

    def test_parse_flag_none(self):
        data = {**SAMPLE_DOC_RESULT, "xbrlFlag": None}
        doc = DocumentMetadata.model_validate(data)
        assert doc.has_xbrl is False

    def test_parse_flag_int(self):
        data = {**SAMPLE_DOC_RESULT, "xbrlFlag": 1}
        doc = DocumentMetadata.model_validate(data)
        assert doc.has_xbrl is True

    def test_parse_nullable_date_none(self):
        doc = DocumentMetadata.model_validate(SAMPLE_DOC_RESULT_NULLABLE)
        assert doc.period_start is None

    def test_parse_nullable_date_empty(self):
        data = {**SAMPLE_DOC_RESULT, "periodStart": ""}
        doc = DocumentMetadata.model_validate(data)
        assert doc.period_start is None

    def test_parse_nullable_date_valid(self):
        doc = DocumentMetadata.model_validate(SAMPLE_DOC_RESULT)
        assert doc.period_start == date(2023, 4, 1)


# ---------------------------------------------------------------------------
# list_documents (mocked)
# ---------------------------------------------------------------------------


class TestListDocuments:
    @respx.mock
    async def test_success(self):
        respx.get(f"{BASE}/documents.json").mock(
            return_value=httpx.Response(200, json=SAMPLE_API_RESPONSE)
        )
        async with EdinetClient(api_key="test-key") as client:
            resp = await client.list_documents(date(2024, 3, 29))

        assert isinstance(resp, DocumentListResponse)
        assert resp.is_success is True
        assert len(resp.results) == 2
        assert resp.results[0].doc_id == "S100ABCD"

    @respx.mock
    async def test_nullable_fields_no_crash(self):
        response = {
            "metadata": {"status": "200", "message": "OK"},
            "results": [SAMPLE_DOC_RESULT_NULLABLE],
        }
        respx.get(f"{BASE}/documents.json").mock(
            return_value=httpx.Response(200, json=response)
        )
        async with EdinetClient(api_key="test-key") as client:
            resp = await client.list_documents(date(2024, 3, 29))

        doc = resp.results[0]
        assert doc.edinet_code is None
        assert doc.period_start is None
        assert doc.has_xbrl is False

    @respx.mock
    async def test_empty_results(self):
        respx.get(f"{BASE}/documents.json").mock(
            return_value=httpx.Response(200, json=EMPTY_API_RESPONSE)
        )
        async with EdinetClient(api_key="test-key") as client:
            resp = await client.list_documents(date(2024, 3, 30))

        assert resp.results == []


# ---------------------------------------------------------------------------
# download_xbrl (mocked)
# ---------------------------------------------------------------------------


class TestDownloadXbrl:
    @respx.mock
    async def test_valid_zip_with_xbrl(self):
        xbrl_content = b"<?xml version='1.0'?><xbrl>test</xbrl>"
        respx.get(f"{BASE}/documents/S100ABCD").mock(
            return_value=httpx.Response(200, content=make_xbrl_zip(xbrl_content))
        )
        async with EdinetClient(api_key="test-key") as client:
            content = await client.download_xbrl("S100ABCD")

        assert content == xbrl_content

    @respx.mock
    async def test_zip_with_only_ixbrl_falls_back(self):
        ixbrl_content = b"<html>inline xbrl</html>"
        respx.get(f"{BASE}/documents/S100ABCD").mock(
            return_value=httpx.Response(200, content=make_ixbrl_zip(ixbrl_content))
        )
        async with EdinetClient(api_key="test-key") as client:
            content = await client.download_xbrl("S100ABCD")

        assert content == ixbrl_content

    @respx.mock
    async def test_no_xbrl_in_zip_raises(self):
        respx.get(f"{BASE}/documents/S100ABCD").mock(
            return_value=httpx.Response(200, content=make_empty_zip())
        )
        async with EdinetClient(api_key="test-key") as client:
            with pytest.raises(EdinetApiError, match="No XBRL instance document"):
                await client.download_xbrl("S100ABCD")

    @respx.mock
    async def test_non_zip_response_raises(self):
        respx.get(f"{BASE}/documents/S100ABCD").mock(
            return_value=httpx.Response(200, content=b"not a zip file")
        )
        async with EdinetClient(api_key="test-key") as client:
            with pytest.raises(EdinetApiError, match="not a valid ZIP"):
                await client.download_xbrl("S100ABCD")


# ---------------------------------------------------------------------------
# DocumentListResponse
# ---------------------------------------------------------------------------


class TestDocumentListResponse:
    def test_is_success_200(self):
        resp = DocumentListResponse(
            metadata={"status": "200", "message": "OK"},
            results=[],
            request_date=date(2024, 3, 29),
        )
        assert resp.is_success is True

    def test_is_success_404(self):
        resp = DocumentListResponse(
            metadata={"status": "404", "message": "Not Found"},
            results=[],
            request_date=date(2024, 3, 29),
        )
        assert resp.is_success is False
