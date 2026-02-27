"""Shared fixtures for edinet-xbrl tests."""

from __future__ import annotations

import io
import zipfile

import pytest

# ---------------------------------------------------------------------------
# XBRL building blocks
# ---------------------------------------------------------------------------

XBRL_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/cor"
  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/cor"
  xmlns:jppfs_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/cor"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
"""

XBRL_FOOTER = "</xbrli:xbrl>"

CONTEXT_CURRENT_YEAR = """\
<xbrli:context id="CurrentYearDuration">
  <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E00001</xbrli:identifier></xbrli:entity>
  <xbrli:period>
    <xbrli:startDate>2023-04-01</xbrli:startDate>
    <xbrli:endDate>2024-03-31</xbrli:endDate>
  </xbrli:period>
</xbrli:context>
<xbrli:context id="CurrentYearInstant">
  <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E00001</xbrli:identifier></xbrli:entity>
  <xbrli:period>
    <xbrli:instant>2024-03-31</xbrli:instant>
  </xbrli:period>
</xbrli:context>
"""

CONTEXT_PRIOR_YEAR = """\
<xbrli:context id="Prior1YearDuration">
  <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E00001</xbrli:identifier></xbrli:entity>
  <xbrli:period>
    <xbrli:startDate>2022-04-01</xbrli:startDate>
    <xbrli:endDate>2023-03-31</xbrli:endDate>
  </xbrli:period>
</xbrli:context>
"""

DEI_JP_GAAP = """\
<jpdei_cor:EDINETCodeDEI contextRef="CurrentYearDuration">E00001</jpdei_cor:EDINETCodeDEI>
<jpdei_cor:SecurityCodeDEI contextRef="CurrentYearDuration">72030</jpdei_cor:SecurityCodeDEI>
<jpdei_cor:FilerNameInJapaneseDEI contextRef="CurrentYearDuration">テスト株式会社</jpdei_cor:FilerNameInJapaneseDEI>
<jpdei_cor:FilerNameInEnglishDEI contextRef="CurrentYearDuration">Test Corp</jpdei_cor:FilerNameInEnglishDEI>
<jpdei_cor:AccountingStandardsDEI contextRef="CurrentYearDuration">Japan GAAP</jpdei_cor:AccountingStandardsDEI>
<jpdei_cor:CurrentFiscalYearStartDateDEI contextRef="CurrentYearDuration">2023-04-01</jpdei_cor:CurrentFiscalYearStartDateDEI>
<jpdei_cor:CurrentFiscalYearEndDateDEI contextRef="CurrentYearDuration">2024-03-31</jpdei_cor:CurrentFiscalYearEndDateDEI>
"""

FINANCIALS_JP_GAAP = """\
<jpcrp_cor:NetSalesSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">1000000</jpcrp_cor:NetSalesSummaryOfBusinessResults>
<jpcrp_cor:OperatingIncomeLossSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">200000</jpcrp_cor:OperatingIncomeLossSummaryOfBusinessResults>
<jpcrp_cor:OrdinaryIncomeLossSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">210000</jpcrp_cor:OrdinaryIncomeLossSummaryOfBusinessResults>
<jpcrp_cor:NetIncomeLossSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">150000</jpcrp_cor:NetIncomeLossSummaryOfBusinessResults>
<jpcrp_cor:TotalAssetsSummaryOfBusinessResults contextRef="CurrentYearInstant" unitRef="JPY" decimals="0">5000000</jpcrp_cor:TotalAssetsSummaryOfBusinessResults>
<jpcrp_cor:NetAssetsSummaryOfBusinessResults contextRef="CurrentYearInstant" unitRef="JPY" decimals="0">3000000</jpcrp_cor:NetAssetsSummaryOfBusinessResults>
<jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPYPerShares" decimals="2">150.50</jpcrp_cor:BasicEarningsLossPerShareSummaryOfBusinessResults>
<jpcrp_cor:CashFlowsFromOperatingActivitiesSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">300000</jpcrp_cor:CashFlowsFromOperatingActivitiesSummaryOfBusinessResults>
<jpcrp_cor:CashFlowsFromInvestingActivitiesSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">-100000</jpcrp_cor:CashFlowsFromInvestingActivitiesSummaryOfBusinessResults>
<jpcrp_cor:CashFlowsFromFinancingActivitiesSummaryOfBusinessResults contextRef="CurrentYearDuration" unitRef="JPY" decimals="0">-50000</jpcrp_cor:CashFlowsFromFinancingActivitiesSummaryOfBusinessResults>
"""

# ---------------------------------------------------------------------------
# Assembled XBRL fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def jp_gaap_xbrl() -> bytes:
    """Minimal valid JP-GAAP traditional XBRL bytes."""
    return (
        XBRL_HEADER
        + '<xbrli:unit id="JPY"><xbrli:measure>iso4217:JPY</xbrli:measure></xbrli:unit>\n'
        + '<xbrli:unit id="JPYPerShares"><xbrli:measure>iso4217:JPY</xbrli:measure></xbrli:unit>\n'
        + CONTEXT_CURRENT_YEAR
        + DEI_JP_GAAP
        + FINANCIALS_JP_GAAP
        + XBRL_FOOTER
    ).encode("utf-8")


@pytest.fixture
def ixbrl_bytes() -> bytes:
    """Minimal valid iXBRL (HTML) bytes."""
    return (
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"\n'
        '      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"\n'
        '      xmlns:xbrli="http://www.xbrl.org/2003/instance"\n'
        '      xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/cor"\n'
        '      xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/cor"\n'
        '      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">\n'
        '<head><title>iXBRL Test</title></head>\n'
        '<body>\n'
        '<div style="display:none">\n'
        '  <xbrli:context id="CurrentYearDuration">\n'
        '    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E00004</xbrli:identifier></xbrli:entity>\n'
        '    <xbrli:period>\n'
        '      <xbrli:startDate>2023-04-01</xbrli:startDate>\n'
        '      <xbrli:endDate>2024-03-31</xbrli:endDate>\n'
        '    </xbrli:period>\n'
        '  </xbrli:context>\n'
        '  <xbrli:context id="CurrentYearInstant">\n'
        '    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E00004</xbrli:identifier></xbrli:entity>\n'
        '    <xbrli:period>\n'
        '      <xbrli:instant>2024-03-31</xbrli:instant>\n'
        '    </xbrli:period>\n'
        '  </xbrli:context>\n'
        '  <xbrli:unit id="JPY"><xbrli:measure>iso4217:JPY</xbrli:measure></xbrli:unit>\n'
        '</div>\n'
        '<ix:nonNumeric name="jpdei_cor:EDINETCodeDEI" contextRef="CurrentYearDuration">E00004</ix:nonNumeric>\n'
        '<ix:nonNumeric name="jpdei_cor:FilerNameInJapaneseDEI" contextRef="CurrentYearDuration">iXBRLテスト社</ix:nonNumeric>\n'
        '<ix:nonNumeric name="jpdei_cor:AccountingStandardsDEI" contextRef="CurrentYearDuration">Japan GAAP</ix:nonNumeric>\n'
        '<ix:nonNumeric name="jpdei_cor:CurrentFiscalYearStartDateDEI" contextRef="CurrentYearDuration">2023-04-01</ix:nonNumeric>\n'
        '<ix:nonNumeric name="jpdei_cor:CurrentFiscalYearEndDateDEI" contextRef="CurrentYearDuration">2024-03-31</ix:nonNumeric>\n'
        '<ix:nonFraction name="jpcrp_cor:NetSalesSummaryOfBusinessResults" contextRef="CurrentYearDuration" unitRef="JPY" decimals="0" scale="6">1</ix:nonFraction>\n'
        '<ix:nonFraction name="jpcrp_cor:NetIncomeLossSummaryOfBusinessResults" contextRef="CurrentYearDuration" unitRef="JPY" decimals="0" sign="-" scale="3">500</ix:nonFraction>\n'
        '<ix:nonFraction name="jpcrp_cor:TotalAssetsSummaryOfBusinessResults" contextRef="CurrentYearInstant" unitRef="JPY" decimals="0" scale="0">5000000</ix:nonFraction>\n'
        '</body>\n'
        '</html>'
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# ZIP helpers
# ---------------------------------------------------------------------------


def make_xbrl_zip(xbrl_content: bytes = b"<?xml version='1.0'?><xbrl/>") -> bytes:
    """Wrap XBRL bytes in a ZIP at XBRL/PublicDoc/filing.xbrl."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/filing.xbrl", xbrl_content)
    return buf.getvalue()


def make_ixbrl_zip(ixbrl_content: bytes = b"<html>ixbrl</html>") -> bytes:
    """Wrap iXBRL bytes in a ZIP at XBRL/PublicDoc/report_ixbrl.htm."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/report_ixbrl.htm", ixbrl_content)
    return buf.getvalue()


def make_empty_zip() -> bytes:
    """ZIP with no XBRL files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other/readme.txt", "no xbrl here")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sample EDINET API JSON responses
# ---------------------------------------------------------------------------

SAMPLE_DOC_RESULT = {
    "docID": "S100ABCD",
    "edinetCode": "E00001",
    "secCode": "72030",
    "filerName": "テスト株式会社",
    "docDescription": "有価証券報告書",
    "docTypeCode": "120",
    "periodStart": "2023-04-01",
    "periodEnd": "2024-03-31",
    "submitDateTime": "2024-06-25 09:30:00",
    "xbrlFlag": "1",
    "pdfFlag": "1",
}

SAMPLE_DOC_RESULT_NULLABLE = {
    "docID": "S100EFGH",
    "edinetCode": None,
    "secCode": None,
    "filerName": "テストファンド",
    "docDescription": "有価証券届出書",
    "docTypeCode": "030",
    "periodStart": None,
    "periodEnd": None,
    "submitDateTime": "2024-06-25 10:00:00",
    "xbrlFlag": "0",
    "pdfFlag": "1",
}

SAMPLE_API_RESPONSE = {
    "metadata": {"status": "200", "message": "OK"},
    "results": [SAMPLE_DOC_RESULT, SAMPLE_DOC_RESULT_NULLABLE],
}

EMPTY_API_RESPONSE = {
    "metadata": {"status": "200", "message": "OK"},
    "results": [],
}
