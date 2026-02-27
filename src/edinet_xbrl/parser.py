"""XBRL/iXBRL parser for EDINET filings.

Parses raw XBRL bytes (from EdinetClient.download_xbrl()) into structured
financial data using the taxonomy built by scripts/build_taxonomy.py.

Memory-efficient: uses lxml.etree.iterparse() with element clearing for
traditional XBRL files (10-50MB). iXBRL (HTML) files are typically 1-5MB
and use full DOM parsing.
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from lxml import etree
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class CompanyInfo(BaseModel):
    """Company identity extracted from DEI elements."""

    edinet_code: str
    name_jp: str
    name_en: str | None = None
    securities_code: str | None = None


class FilingMetadata(BaseModel):
    """Filing-level metadata."""

    doc_id: str
    period_start: date | None = None
    period_end: date | None = None
    fiscal_year: int | None = None
    accounting_standard: Literal["JP-GAAP", "IFRS", "US-GAAP"] = "JP-GAAP"
    filing_type: str = "annual"
    filed_at: datetime | None = None


class FinancialValue(BaseModel):
    """A single extracted financial value."""

    field_name: str
    value: int | None = None
    currency: str = "JPY"
    context_ref: str = ""
    is_per_share: bool = False
    decimals: int | None = None


class ParsedFiling(BaseModel):
    """Complete parsed output from an XBRL filing."""

    company: CompanyInfo
    metadata: FilingMetadata
    financials: list[FinancialValue]
    raw_elements: dict[str, str]
    parse_warnings: list[str]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PER_SHARE_FIELDS = {"eps", "diluted_eps", "dividends_per_share", "bps"}

_CURRENT_YEAR_PATTERNS = re.compile(
    r"CurrentYear|Prior0Year",
    re.IGNORECASE,
)

_CONSOLIDATED_PATTERN = re.compile(r"(?<!Non)Consolidated", re.IGNORECASE)

_STANDARD_DEI_MAP = {
    "Japan GAAP": "JP-GAAP",
    "日本基準": "JP-GAAP",
    "IFRS": "IFRS",
    "US GAAP": "US-GAAP",
    "米国基準": "US-GAAP",
}

_ENCODING_RE = re.compile(rb'encoding=["\']([^"\']+)["\']', re.IGNORECASE)

_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_IX_NS_SET = {
    "http://www.xbrl.org/2013/inlineXBRL",
    "http://www.xbrl.org/2008/inlineXBRL",
    "http://www.xbrl.org/CR-2013-08-07/inlineXBRL",
}

_NON_UTF8_ENCODINGS = {
    "shift_jis", "shift-jis", "sjis",
    "euc-jp", "euc_jp", "iso-2022-jp",
}


# ---------------------------------------------------------------------------
# XBRLParser
# ---------------------------------------------------------------------------


class XBRLParser:
    """Parse XBRL/iXBRL bytes into structured financial data.

    Loads taxonomy.json once on init (~200KB). Thread-safe for concurrent
    parse() calls since taxonomy is read-only after init.
    """

    def __init__(self, taxonomy_path: Path | None = None) -> None:
        if taxonomy_path is None:
            taxonomy_path = Path(__file__).parent / "taxonomy.json"
        with open(taxonomy_path, encoding="utf-8") as f:
            self._field_map: dict[str, dict] = json.load(f)["field_map"]

    def parse(self, xbrl_bytes: bytes, doc_id: str = "") -> ParsedFiling:
        """Parse XBRL or iXBRL bytes into a ParsedFiling."""
        if _is_ixbrl(xbrl_bytes):
            return self._parse_ixbrl(xbrl_bytes, doc_id)
        return self._parse_xbrl(xbrl_bytes, doc_id)

    # -------------------------------------------------------------------
    # Traditional XBRL (streaming)
    # -------------------------------------------------------------------

    def _parse_xbrl(self, xbrl_bytes: bytes, doc_id: str) -> ParsedFiling:
        """Memory-efficient streaming parse of traditional XBRL."""
        xbrl_bytes = _ensure_utf8(xbrl_bytes)

        dei_values: dict[str, str] = {}
        raw_values: dict[str, list[tuple[str, str, str]]] = {}
        raw_elements: dict[str, str] = {}
        contexts: dict[str, dict] = {}
        namespaces: dict[str, str] = {}

        context_tag = f"{{{_XBRLI_NS}}}context"

        for event, elem in etree.iterparse(
            io.BytesIO(xbrl_bytes), events=("start-ns", "end")
        ):
            if event == "start-ns":
                prefix, uri = elem
                if prefix:
                    namespaces[prefix] = uri
                continue

            tag = elem.tag

            if tag == context_tag:
                ctx_id = elem.get("id", "")
                if ctx_id:
                    contexts[ctx_id] = _parse_context(elem)
                elem.clear()
                continue

            if "}" not in tag:
                elem.clear()
                continue

            ns_uri, local = tag[1:].split("}", 1)
            if ns_uri == _XBRLI_NS:
                elem.clear()
                continue

            prefix = _find_prefix(namespaces, ns_uri)
            if prefix is None:
                elem.clear()
                continue

            text = (elem.text or "").strip()
            context_ref = elem.get("contextRef", "")
            decimals_str = elem.get("decimals", "")
            elem_id = f"{prefix}:{local}"

            self._collect_value(
                elem_id, text, context_ref, decimals_str,
                dei_values, raw_values, raw_elements,
            )
            elem.clear()

        return self._assemble(
            dei_values, raw_values, raw_elements,
            contexts, namespaces, doc_id,
        )

    # -------------------------------------------------------------------
    # Inline XBRL (iXBRL) — full DOM
    # -------------------------------------------------------------------

    def _parse_ixbrl(self, xbrl_bytes: bytes, doc_id: str) -> ParsedFiling:
        """Parse inline XBRL (HTML with ix: tags)."""
        xbrl_bytes = _ensure_utf8(xbrl_bytes)

        try:
            tree = etree.fromstring(xbrl_bytes)
        except etree.XMLSyntaxError:
            tree = etree.fromstring(xbrl_bytes, etree.HTMLParser())

        nsmap = _collect_nsmap(tree)

        dei_values: dict[str, str] = {}
        raw_values: dict[str, list[tuple[str, str, str]]] = {}
        raw_elements: dict[str, str] = {}
        contexts: dict[str, dict] = {}

        # Discover which ix namespace this document uses
        ix_ns = _find_ix_namespace(nsmap, tree)

        for ctx_elem in tree.iter(f"{{{_XBRLI_NS}}}context"):
            ctx_id = ctx_elem.get("id", "")
            if ctx_id:
                contexts[ctx_id] = _parse_context(ctx_elem)

        if ix_ns:
            for elem in tree.iter(f"{{{ix_ns}}}nonFraction"):
                name = elem.get("name", "")
                text = _ix_text_content(elem)
                if not name or not text:
                    continue

                numeric = _parse_numeric(text)
                if numeric is not None:
                    scale = int(elem.get("scale", "0") or "0")
                    if scale:
                        numeric = int(numeric * (10**scale))
                    if elem.get("sign") == "-":
                        numeric = -numeric
                    text = str(numeric)

                self._collect_value(
                    name, text, elem.get("contextRef", ""),
                    elem.get("decimals", ""),
                    dei_values, raw_values, raw_elements,
                )

            for elem in tree.iter(f"{{{ix_ns}}}nonNumeric"):
                name = elem.get("name", "")
                text = _ix_text_content(elem)
                if not name or not text:
                    continue
                self._collect_value(
                    name, text, elem.get("contextRef", ""), "",
                    dei_values, raw_values, raw_elements,
                )

        return self._assemble(
            dei_values, raw_values, raw_elements,
            contexts, nsmap, doc_id,
        )

    # -------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------

    def _collect_value(
        self,
        elem_id: str,
        text: str,
        context_ref: str,
        decimals_str: str,
        dei_values: dict[str, str],
        raw_values: dict[str, list[tuple[str, str, str]]],
        raw_elements: dict[str, str],
    ) -> None:
        """Route an element value to DEI, raw_values, or raw_elements."""
        if not text:
            return
        field_info = self._field_map.get(elem_id)
        if field_info and field_info["category"] == "dei":
            dei_values[field_info["field"]] = text
        elif field_info:
            raw_values.setdefault(elem_id, []).append(
                (text, context_ref, decimals_str)
            )
        else:
            raw_elements[elem_id] = text

    def _assemble(
        self,
        dei_values: dict[str, str],
        raw_values: dict[str, list[tuple[str, str, str]]],
        raw_elements: dict[str, str],
        contexts: dict[str, dict],
        namespaces: dict[str, str],
        doc_id: str,
    ) -> ParsedFiling:
        """Build ParsedFiling from collected raw data."""
        warnings: list[str] = []
        current_year_ctx, consolidated_ctx = _build_context_sets(contexts)

        standard = _detect_standard_from_dei(dei_values)
        if standard is None:
            standard = _detect_standard_from_namespaces(namespaces)

        return ParsedFiling(
            company=_build_company_info(dei_values, warnings),
            metadata=_build_metadata(dei_values, doc_id, standard),
            financials=self._resolve_financials(
                raw_values, current_year_ctx, consolidated_ctx,
            ),
            raw_elements=raw_elements,
            parse_warnings=warnings,
        )

    def _resolve_financials(
        self,
        raw_values: dict[str, list[tuple[str, str, str]]],
        current_year_ctx: set[str],
        consolidated_ctx: set[str],
    ) -> list[FinancialValue]:
        """Resolve raw values into deduplicated FinancialValue list."""
        seen: dict[str, FinancialValue] = {}

        for elem_id, entries in raw_values.items():
            field_info = self._field_map.get(elem_id)
            if not field_info:
                continue

            field_name = field_info["field"]
            if field_name in seen:
                continue

            best = _pick_best_entry(entries, current_year_ctx, consolidated_ctx)
            if best is None:
                continue

            text, context_ref, decimals_str = best
            decimals = _parse_decimals(decimals_str)

            seen[field_name] = FinancialValue(
                field_name=field_name,
                value=_parse_numeric(text),
                currency="JPY",
                context_ref=context_ref,
                is_per_share=field_name in PER_SHARE_FIELDS,
                decimals=decimals,
            )

        return list(seen.values())


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _is_ixbrl(data: bytes) -> bool:
    """Detect inline XBRL (HTML) vs traditional XBRL (XML)."""
    head = data[:4096].lower()
    return b"<html" in head or b"<!doctype html" in head


def _ensure_utf8(data: bytes) -> bytes:
    """Transcode Shift-JIS/EUC-JP to UTF-8 if needed."""
    match = _ENCODING_RE.search(data[:200])
    if match:
        declared = match.group(1).decode("ascii").lower()
        if declared in _NON_UTF8_ENCODINGS:
            text = data.decode(declared, errors="replace")
            text = re.sub(
                r'encoding=["\'][^"\']+["\']',
                'encoding="UTF-8"',
                text,
                count=1,
            )
            return text.encode("utf-8")
    return data


def _parse_numeric(text: str) -> int | None:
    """Parse a Japanese financial numeric string to int.

    Handles commas, spaces, dashes (→None), triangle/parenthesis negatives.
    """
    if not text:
        return None

    text = text.strip()
    if text in ("-", "－", "―", "‐", "–", "—", "△", "…"):
        return None

    text = (text.replace(",", "").replace("，", "")
            .replace(" ", "").replace("\u3000", ""))

    negative = False
    if text.startswith(("△", "▲")):
        negative = True
        text = text[1:]
    elif text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    elif text.startswith(("-", "－", "−")):
        negative = True
        text = text[1:]

    text = text.strip()
    if not text:
        return None

    try:
        result = round(float(text)) if "." in text else int(text)
        return -result if negative else result
    except (ValueError, OverflowError):
        return None


def _parse_decimals(s: str) -> int | None:
    """Parse decimals attribute, ignoring 'INF' and empty strings."""
    if not s or s == "INF":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_context(elem: etree._Element) -> dict:
    """Extract period info from an xbrli:context element."""
    info: dict[str, str] = {"id": elem.get("id", "")}
    period = elem.find(f"{{{_XBRLI_NS}}}period")
    if period is not None:
        for tag, key in (("startDate", "start"), ("endDate", "end"), ("instant", "instant")):
            child = period.find(f"{{{_XBRLI_NS}}}{tag}")
            if child is not None and child.text:
                info[key] = child.text.strip()
    return info


def _build_context_sets(
    contexts: dict[str, dict],
) -> tuple[set[str], set[str]]:
    """Build current-year and consolidated context ID sets."""
    current_year: set[str] = set()
    consolidated: set[str] = set()

    for ctx_id in contexts:
        if _CURRENT_YEAR_PATTERNS.search(ctx_id):
            current_year.add(ctx_id)
        if "NonConsolidated" not in ctx_id:
            consolidated.add(ctx_id)

    if not current_year:
        current_year = set(contexts.keys())

    return current_year, consolidated


def _pick_best_entry(
    entries: list[tuple[str, str, str]],
    current_year_ctx: set[str],
    consolidated_ctx: set[str],
) -> tuple[str, str, str] | None:
    """Pick best entry: current-year consolidated > current-year > first."""
    for entry in entries:
        if entry[1] in current_year_ctx and entry[1] in consolidated_ctx:
            return entry
    for entry in entries:
        if entry[1] in current_year_ctx:
            return entry
    return entries[0] if entries else None


def _detect_standard_from_dei(dei_values: dict[str, str]) -> str | None:
    """Detect accounting standard from DEI value."""
    return _STANDARD_DEI_MAP.get(dei_values.get("accounting_standard", ""))


def _detect_standard_from_namespaces(namespaces: dict[str, str]) -> str:
    """Fall back to namespace prefixes for standard detection."""
    prefixes = " ".join(namespaces.keys()) if namespaces else ""
    if "ifrs-full" in prefixes or "jpigp_cor" in prefixes:
        return "IFRS"
    if "us-gaap" in prefixes:
        return "US-GAAP"
    return "JP-GAAP"


def _build_company_info(
    dei_values: dict[str, str], warnings: list[str],
) -> CompanyInfo:
    """Build CompanyInfo from DEI values."""
    edinet_code = dei_values.get("edinet_code", "")
    name_jp = dei_values.get("company_name_jp", "")
    if not edinet_code:
        warnings.append("Missing DEI: edinet_code")
    if not name_jp:
        warnings.append("Missing DEI: company_name_jp")

    sec_code = dei_values.get("security_code")
    if sec_code and len(sec_code) == 5 and sec_code.endswith("0"):
        sec_code = sec_code[:4]

    return CompanyInfo(
        edinet_code=edinet_code,
        name_jp=name_jp,
        name_en=dei_values.get("company_name_en"),
        securities_code=sec_code,
    )


def _build_metadata(
    dei_values: dict[str, str], doc_id: str, standard: str,
) -> FilingMetadata:
    """Build FilingMetadata from DEI values."""
    period_end = _parse_date(dei_values.get("fiscal_year_end"))
    return FilingMetadata(
        doc_id=doc_id,
        period_start=_parse_date(dei_values.get("fiscal_year_start")),
        period_end=period_end,
        fiscal_year=period_end.year if period_end else None,
        accounting_standard=standard,
    )


def _parse_date(text: str | None) -> date | None:
    """Parse ISO 8601 date string."""
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        return None


def _find_prefix(namespaces: dict[str, str], uri: str) -> str | None:
    """Find namespace prefix for a URI."""
    for prefix, ns_uri in namespaces.items():
        if ns_uri == uri:
            return prefix
    return None


def _find_ix_namespace(
    nsmap: dict[str, str], tree: etree._Element,
) -> str | None:
    """Find the inline XBRL namespace URI used in this document."""
    for uri in nsmap.values():
        if uri in _IX_NS_SET:
            return uri
    for uri in _IX_NS_SET:
        if tree.find(f".//{{{uri}}}nonFraction") is not None:
            return uri
    return None


def _collect_nsmap(tree: etree._Element) -> dict[str, str]:
    """Collect all namespace prefix→URI mappings from an element tree."""
    nsmap: dict[str, str] = {}
    for elem in tree.iter():
        if hasattr(elem, "nsmap") and elem.nsmap:
            for prefix, uri in elem.nsmap.items():
                if prefix and uri:
                    nsmap[prefix] = uri
    return nsmap


def _ix_text_content(elem: etree._Element) -> str:
    """Get text content of an ix: element, handling nested elements."""
    return "".join(elem.itertext()).strip()
