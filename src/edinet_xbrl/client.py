"""EDINET API v2 async client for Japanese financial filings."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import zipfile
from datetime import date, datetime, timedelta
from typing import AsyncGenerator

import httpx
from pydantic import BaseModel, Field, field_validator
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class EdinetApiError(Exception):
    """Raised for all EDINET API errors."""

    def __init__(self, status_code: int, message: str, doc_id: str | None = None):
        self.status_code = status_code
        self.message = message
        self.doc_id = doc_id
        super().__init__(f"EDINET API error {status_code}: {message}")


class DocumentMetadata(BaseModel):
    """Metadata for a single EDINET filing document."""

    doc_id: str = Field(alias="docID")
    edinet_code: str | None = Field(default=None, alias="edinetCode")
    sec_code: str | None = Field(default=None, alias="secCode")
    filer_name: str | None = Field(default=None, alias="filerName")
    doc_description: str | None = Field(default=None, alias="docDescription")
    doc_type_code: str | None = Field(default=None, alias="docTypeCode")
    period_start: date | None = Field(default=None, alias="periodStart")
    period_end: date | None = Field(default=None, alias="periodEnd")
    submit_date_time: datetime | None = Field(default=None, alias="submitDateTime")
    has_xbrl: bool = Field(alias="xbrlFlag")
    has_pdf: bool = Field(alias="pdfFlag")

    model_config = {"populate_by_name": True}

    @field_validator("has_xbrl", "has_pdf", mode="before")
    @classmethod
    def parse_flag(cls, v: str | bool | int | None) -> bool:
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return v == 1
        return str(v) == "1"

    @field_validator("period_start", "period_end", mode="before")
    @classmethod
    def parse_nullable_date(cls, v: str | None) -> date | None:
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        return date.fromisoformat(v)


class DocumentListResponse(BaseModel):
    """Response from the EDINET document listing endpoint."""

    metadata: dict
    results: list[DocumentMetadata]
    request_date: date

    @property
    def is_success(self) -> bool:
        return str(self.metadata.get("status")) == "200"


def _is_retryable(exc: BaseException) -> bool:
    """Check if an exception should trigger a retry."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout))


class EdinetClient:
    """Async client for the EDINET API v2."""

    BASE_URL = "https://api.edinet-fsa.go.jp/api/v2"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        api_key = api_key or os.environ.get("EDINET_API_KEY")
        if not api_key:
            raise ValueError(
                "EDINET API key is required. Pass api_key or set EDINET_API_KEY env var."
            )
        self._api_key = api_key
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(10)

    async def __aenter__(self) -> EdinetClient:
        self._client = httpx.AsyncClient(
            headers={"Ocp-Apim-Subscription-Key": self._api_key},
            timeout=self._timeout,
        )
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "EdinetClient must be used as an async context manager: "
                "'async with EdinetClient(...) as client:'"
            )
        return self._client

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> httpx.Response:
        """Make an HTTP request with rate limiting and retry."""
        client = self._ensure_client()
        url = f"{self.BASE_URL}{path}"

        async with self._semaphore:
            logger.debug("EDINET API %s %s params=%s", method, url, params)
            response = await client.request(method, url, params=params)

            if response.status_code >= 400:
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise EdinetApiError(
                        status_code=response.status_code,
                        message=response.text,
                    )
                response.raise_for_status()

            return response

    async def list_documents(
        self, query_date: date, doc_type: int = 2
    ) -> DocumentListResponse:
        """List documents filed on a specific date.

        Args:
            query_date: The date to query for filings.
            doc_type: Document type filter (1=metadata only, 2=with documents).

        Returns:
            DocumentListResponse with parsed document metadata.
        """
        response = await self._request(
            "GET",
            "/documents.json",
            params={"date": query_date.isoformat(), "type": str(doc_type)},
        )
        data = response.json()

        metadata = data.get("metadata", {})
        results_raw = data.get("results", []) or []

        results = [DocumentMetadata.model_validate(r) for r in results_raw]

        return DocumentListResponse(
            metadata=metadata,
            results=results,
            request_date=query_date,
        )

    async def list_documents_range(
        self, start: date, end: date
    ) -> AsyncGenerator[DocumentListResponse, None]:
        """Iterate over documents filed in a date range (inclusive).

        Yields one DocumentListResponse per day.
        """
        current = start
        while current <= end:
            yield await self.list_documents(current)
            current += timedelta(days=1)

    async def download_document(self, doc_id: str, doc_type: int = 1) -> bytes:
        """Download a document archive as raw ZIP bytes.

        Args:
            doc_id: EDINET document ID (e.g. "S100ABCD").
            doc_type: Download type (1=ZIP with XBRL, 2=PDF, 5=CSV).

        Returns:
            Raw bytes of the ZIP archive.

        Raises:
            EdinetApiError: If the download fails or response is not a valid ZIP.
        """
        response = await self._request(
            "GET",
            f"/documents/{doc_id}",
            params={"type": str(doc_type)},
        )
        content = response.content

        if not content.startswith(b"PK"):
            raise EdinetApiError(
                status_code=response.status_code,
                message="Response is not a valid ZIP file",
                doc_id=doc_id,
            )

        return content

    async def download_xbrl(self, doc_id: str) -> bytes:
        """Download and extract the XBRL instance document from a filing.

        Downloads the ZIP archive, then extracts the XBRL file from
        XBRL/PublicDoc/ directory.

        Args:
            doc_id: EDINET document ID.

        Returns:
            Raw bytes of the XBRL instance document.

        Raises:
            EdinetApiError: If download fails, ZIP is invalid, or no XBRL found.
        """
        zip_bytes = await self.download_document(doc_id)

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                # Prefer .xbrl instance (contains all data) over _ixbrl.htm
                # fragments which only contain one section each.
                xbrl_file = None
                ixbrl_file = None
                for name in zf.namelist():
                    if "XBRL/PublicDoc/" not in name:
                        continue
                    if name.endswith(".xbrl"):
                        xbrl_file = name
                        break  # .xbrl is always preferred
                    if name.endswith("_ixbrl.htm") and ixbrl_file is None:
                        ixbrl_file = name

                chosen = xbrl_file or ixbrl_file
                if chosen:
                    return zf.read(chosen)

                raise EdinetApiError(
                    status_code=0,
                    message="No XBRL instance document found in archive",
                    doc_id=doc_id,
                )
        except zipfile.BadZipFile:
            raise EdinetApiError(
                status_code=0,
                message="Downloaded file is not a valid ZIP archive",
                doc_id=doc_id,
            )
