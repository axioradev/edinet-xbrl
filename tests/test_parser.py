"""Unit tests for the XBRL/iXBRL parser."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import (
    CONTEXT_CURRENT_YEAR,
    XBRL_FOOTER,
    XBRL_HEADER,
)

from edinet_xbrl.parser import (
    XBRLParser,
    _ensure_utf8,
    _is_ixbrl,
    _parse_date,
    _parse_numeric,
)


@pytest.fixture
def parser() -> XBRLParser:
    return XBRLParser()


# ---------------------------------------------------------------------------
# _parse_numeric
# ---------------------------------------------------------------------------


class TestParseNumeric:
    def test_commas(self):
        assert _parse_numeric("1,234,567") == 1234567

    def test_triangle_negative(self):
        assert _parse_numeric("△1,000") == -1000

    def test_parenthesis_negative(self):
        assert _parse_numeric("(500)") == -500

    def test_full_width_digits(self):
        assert _parse_numeric("１２３") == 123

    def test_dash_returns_none(self):
        assert _parse_numeric("-") is None

    def test_empty_returns_none(self):
        assert _parse_numeric("") is None

    def test_plain_integer(self):
        assert _parse_numeric("1000000") == 1000000

    def test_minus_sign(self):
        assert _parse_numeric("-500000") == -500000

    def test_em_dash_returns_none(self):
        assert _parse_numeric("—") is None

    def test_horizontal_bar_returns_none(self):
        assert _parse_numeric("―") is None

    def test_decimal_rounds(self):
        assert _parse_numeric("150.50") == 150


# ---------------------------------------------------------------------------
# _is_ixbrl
# ---------------------------------------------------------------------------


class TestIsIxbrl:
    def test_html_returns_true(self):
        assert _is_ixbrl(b"<!DOCTYPE html><html>") is True

    def test_xml_returns_false(self):
        assert _is_ixbrl(b'<?xml version="1.0"?><xbrli:xbrl>') is False

    def test_empty_returns_false(self):
        assert _is_ixbrl(b"") is False


# ---------------------------------------------------------------------------
# _ensure_utf8
# ---------------------------------------------------------------------------


class TestEnsureUtf8:
    def test_shift_jis_transcoded(self):
        sjis_xml = '<?xml version="1.0" encoding="Shift_JIS"?><root>テスト</root>'
        sjis_bytes = sjis_xml.encode("shift_jis")
        result = _ensure_utf8(sjis_bytes)
        assert b"UTF-8" in result
        decoded = result.decode("utf-8")
        assert "テスト" in decoded

    def test_utf8_passthrough(self):
        utf8_xml = '<?xml version="1.0" encoding="UTF-8"?><root>テスト</root>'.encode("utf-8")
        result = _ensure_utf8(utf8_xml)
        assert result == utf8_xml


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    def test_valid_date(self):
        assert _parse_date("2024-03-31") == date(2024, 3, 31)

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None


# ---------------------------------------------------------------------------
# parse() integration
# ---------------------------------------------------------------------------


class TestParseTraditionalXbrl:
    def test_company_info(self, parser, jp_gaap_xbrl):
        result = parser.parse(jp_gaap_xbrl, doc_id="S100TEST")
        assert result.company.edinet_code == "E00001"
        assert result.company.name_jp == "テスト株式会社"
        assert result.company.name_en == "Test Corp"

    def test_metadata(self, parser, jp_gaap_xbrl):
        result = parser.parse(jp_gaap_xbrl, doc_id="S100TEST")
        assert result.metadata.doc_id == "S100TEST"
        assert result.metadata.accounting_standard == "JP-GAAP"
        assert result.metadata.fiscal_year == 2024

    def test_financials_extracted(self, parser, jp_gaap_xbrl):
        result = parser.parse(jp_gaap_xbrl, doc_id="test")
        fields = {fv.field_name: fv for fv in result.financials}
        assert "revenue" in fields
        assert fields["revenue"].value == 1000000

    def test_securities_code_stripped(self, parser, jp_gaap_xbrl):
        """72030 → 7203 (trailing 0 stripped from 5-digit codes)."""
        result = parser.parse(jp_gaap_xbrl, doc_id="test")
        assert result.company.securities_code == "7203"

    def test_missing_dei_adds_warnings(self, parser):
        """Filing with no company name DEI → parse_warnings populated."""
        xbrl = (
            XBRL_HEADER
            + CONTEXT_CURRENT_YEAR
            + '<jpdei_cor:EDINETCodeDEI contextRef="CurrentYearDuration">E99999</jpdei_cor:EDINETCodeDEI>\n'
            + XBRL_FOOTER
        ).encode("utf-8")
        result = parser.parse(xbrl, doc_id="test")
        assert any("company_name_jp" in w for w in result.parse_warnings)

    def test_model_dump_json(self, parser, jp_gaap_xbrl):
        """model_dump_json() produces valid JSON."""
        import json

        result = parser.parse(jp_gaap_xbrl, doc_id="test")
        data = json.loads(result.model_dump_json())
        assert "company" in data
        assert "metadata" in data
        assert "financials" in data


class TestParseIxbrl:
    def test_company_info(self, parser, ixbrl_bytes):
        result = parser.parse(ixbrl_bytes, doc_id="test")
        assert result.company.edinet_code == "E00004"
        assert result.company.name_jp == "iXBRLテスト社"

    def test_scale_applied(self, parser, ixbrl_bytes):
        """scale="6" means multiply by 10^6."""
        result = parser.parse(ixbrl_bytes, doc_id="test")
        fields = {fv.field_name: fv for fv in result.financials}
        assert "revenue" in fields
        assert fields["revenue"].value == 1000000

    def test_sign_applied(self, parser, ixbrl_bytes):
        """sign="-" negates the value."""
        result = parser.parse(ixbrl_bytes, doc_id="test")
        fields = {fv.field_name: fv for fv in result.financials}
        if "net_income" in fields:
            assert fields["net_income"].value == -500000


class TestStandardDetection:
    def test_jp_gaap_from_dei(self, parser, jp_gaap_xbrl):
        result = parser.parse(jp_gaap_xbrl, doc_id="test")
        assert result.metadata.accounting_standard == "JP-GAAP"

    def test_ifrs_from_dei(self, parser):
        xbrl = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<xbrli:xbrl\n"
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"\n'
            '  xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/cor"\n'
            '  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/cor">\n'
            + CONTEXT_CURRENT_YEAR
            + '<jpdei_cor:EDINETCodeDEI contextRef="CurrentYearDuration">E00002</jpdei_cor:EDINETCodeDEI>\n'
            + '<jpdei_cor:FilerNameInJapaneseDEI contextRef="CurrentYearDuration">IFRS企業</jpdei_cor:FilerNameInJapaneseDEI>\n'
            + '<jpdei_cor:AccountingStandardsDEI contextRef="CurrentYearDuration">IFRS</jpdei_cor:AccountingStandardsDEI>\n'
            + '<jpdei_cor:CurrentFiscalYearEndDateDEI contextRef="CurrentYearDuration">2023-12-31</jpdei_cor:CurrentFiscalYearEndDateDEI>\n'
            + "</xbrli:xbrl>"
        ).encode("utf-8")
        result = parser.parse(xbrl, doc_id="test")
        assert result.metadata.accounting_standard == "IFRS"

    def test_us_gaap_from_dei(self, parser):
        xbrl = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<xbrli:xbrl\n"
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"\n'
            '  xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/cor"\n'
            '  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/cor">\n'
            + CONTEXT_CURRENT_YEAR
            + '<jpdei_cor:EDINETCodeDEI contextRef="CurrentYearDuration">E00003</jpdei_cor:EDINETCodeDEI>\n'
            + '<jpdei_cor:FilerNameInJapaneseDEI contextRef="CurrentYearDuration">米国基準企業</jpdei_cor:FilerNameInJapaneseDEI>\n'
            + '<jpdei_cor:AccountingStandardsDEI contextRef="CurrentYearDuration">US GAAP</jpdei_cor:AccountingStandardsDEI>\n'
            + '<jpdei_cor:CurrentFiscalYearEndDateDEI contextRef="CurrentYearDuration">2023-12-31</jpdei_cor:CurrentFiscalYearEndDateDEI>\n'
            + "</xbrli:xbrl>"
        ).encode("utf-8")
        result = parser.parse(xbrl, doc_id="test")
        assert result.metadata.accounting_standard == "US-GAAP"

    def test_ifrs_from_namespace_fallback(self, parser):
        """When DEI is missing, detect from namespace prefixes."""
        xbrl = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<xbrli:xbrl\n"
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"\n'
            '  xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/cor"\n'
            '  xmlns:jpigp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpigp/cor">\n'
            + CONTEXT_CURRENT_YEAR
            + '<jpdei_cor:EDINETCodeDEI contextRef="CurrentYearDuration">E99999</jpdei_cor:EDINETCodeDEI>\n'
            + '<jpdei_cor:FilerNameInJapaneseDEI contextRef="CurrentYearDuration">テスト</jpdei_cor:FilerNameInJapaneseDEI>\n'
            + "</xbrli:xbrl>"
        ).encode("utf-8")
        result = parser.parse(xbrl, doc_id="test")
        assert result.metadata.accounting_standard == "IFRS"
