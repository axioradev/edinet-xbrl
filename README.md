<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo-light.svg" width="280">
    <source media="(prefers-color-scheme: light)" srcset="logo-dark.svg" width="280">
    <img alt="Axiora" src="logo-dark.svg" width="280">
  </picture>
</p>

<hr>

<div align="center">
  <a href="https://github.com/axioradev/edinet-xbrl/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/axioradev/edinet-xbrl/actions/workflows/ci.yml/badge.svg"/></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.12+" src="https://img.shields.io/badge/python-3.12%2B-blue.svg"/></a>
  <a href="https://github.com/axioradev/edinet-xbrl/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Modified_MIT-f5de53?&color=f5de53"/></a>
  <a href="https://x.com/axioradev"><img alt="X (Twitter)" src="https://img.shields.io/badge/@axioradev-black?logo=x&logoColor=white"/></a>
</div>

<br>

Parse EDINET XBRL filings into structured JSON. JP-GAAP, IFRS, and US-GAAP. Async. Taxonomy-driven — no hard-coded element IDs.

## The problem

Getting structured financials from Japanese companies means downloading ZIP archives from EDINET, extracting XBRL, guessing which XML elements map to "revenue" vs "net sales" vs "売上高", handling three accounting standards, dealing with iXBRL-wrapped HTML, and normalizing values that use △ for negatives and Japanese-style parentheses. That's 2–4 weeks of engineering before you see a single number.

This parser does it in 5 lines.

## Why not use an existing parser?

There are several open-source EDINET parsers. Each has trade-offs:

| Parser | Strengths | Gaps |
|--------|-----------|------|
| [arelle](https://github.com/Arelle/Arelle) | Industry standard, full spec compliance | 200MB install, designed for validation not extraction |
| [edinet-tools](https://github.com/matthelmer/edinet-tools) | Actively maintained, JP-GAAP + IFRS | No iXBRL support (~60% of recent filings), no context resolution |
| [edinet-mcp](https://github.com/ajtgjmdjp/edinet-mcp) | 161 fields, three standards | No iXBRL, binary non-consolidated filter zeroes out standalone filers |
| [xbrr](https://github.com/chakki-works/xbrr) | Clean API | Unmaintained since 2019, manual context resolution |
| [edinet_xbrl](https://github.com/BuffettCode/edinet_xbrl) | On PyPI | Last release Jan 2018, pre-iXBRL era |

The common gap: **context priority**. A single filing contains the same element in 10+ contexts — consolidated current year, non-consolidated, prior year, by segment. Picking the right one requires knowing whether the filer has consolidated data, whether the context carries dimension members, and which standard's elements take priority. This parser handles that.

Deep dive: [How We Parse 4,125 Companies' XBRL — Without an LLM](https://axiora.dev/en/blog/how-we-parse-xbrl)

## Install

```bash
pip install git+https://github.com/axioradev/edinet-xbrl.git
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/axioradev/edinet-xbrl.git
```

## Quick start

### Download and parse a filing

```python
import asyncio
from datetime import date
from edinet_xbrl import EdinetClient, XBRLParser

async def main():
    parser = XBRLParser()

    async with EdinetClient(api_key="YOUR_KEY") as client:
        # List filings from a specific date
        response = await client.list_documents(date(2025, 3, 31))
        for doc in response.results:
            if doc.has_xbrl and doc.doc_type_code == "120":  # Annual report (有報)
                xbrl_bytes = await client.download_xbrl(doc.doc_id)
                result = parser.parse(xbrl_bytes, doc_id=doc.doc_id)

                print(result.company.name_jp)
                print(result.metadata.accounting_standard)
                for v in result.financials:
                    print(f"  {v.field_name}: {v.value:,} JPY")
                break

asyncio.run(main())
```

### Parse a local file

```python
from edinet_xbrl import XBRLParser

parser = XBRLParser()

with open("path/to/filing.xbrl", "rb") as f:
    result = parser.parse(f.read(), doc_id="S100ABCD")

print(result.company.name_jp)       # トヨタ自動車株式会社
print(result.company.edinet_code)   # E02144
print(result.metadata.accounting_standard)  # JP-GAAP
```

Output:

```
revenue: 37,154,298,000,000 JPY
operating_income: 2,725,025,000,000 JPY
net_income: 2,451,318,000,000 JPY
total_assets: 67,688,771,000,000 JPY
eps: 17439 JPY
```

### JSON export

Pydantic models, so this is built in:

```python
print(result.model_dump_json(indent=2))
```

## EDINET API key (free)

The EDINET client needs an API key from Japan's FSA. It's free:

1. Read the [EDINET API spec](https://disclosure2dl.edinet-fsa.go.jp/guide/static/disclosure/WEEK0060.html) (Japanese)
2. Register at the [API key page](https://api.edinet-fsa.go.jp/api/auth/index.aspx?mode=1)
3. Set it: `export EDINET_API_KEY="your-key-here"`

Or pass directly to `EdinetClient(api_key="...")`.

## How it works

```
                    ┌────────────────────┐
                    │   taxonomy.json    │  Element ID → field mapping
                    └────────┬───────────┘  (~200KB, checked into repo)
                             │
  XBRL bytes ──────►┌───────▼──────────┐
                    │    XBRLParser    │
                    │                  │
                    │  detect format   │──► traditional XBRL → streaming iterparse
                    │  detect encoding │──► iXBRL (HTML)     → full DOM parse
                    │  detect standard │──► JP-GAAP / IFRS / US-GAAP
                    │  resolve context │──► current-year, consolidated
                    │  normalize values│──► handle △, (), commas, scale
                    └───────┬──────────┘
                            │
                    ┌───────▼──────────┐
                    │  ParsedFiling    │  Pydantic model → JSON
                    │  .company        │
                    │  .metadata       │
                    │  .financials[]   │
                    │  .raw_elements   │
                    │  .parse_warnings │
                    └──────────────────┘
```

Most EDINET parsers hard-code XBRL element IDs. When the FSA updates the taxonomy (next major overhaul: 2027 ISSB alignment), those parsers break. This parser uses `taxonomy.json` — a pre-built lookup table mapping element IDs to normalized field names, generated from the official FSA taxonomy. We update the file when new taxonomy versions ship.

## Output structure

```python
result.company          # CompanyInfo
  .edinet_code          #   "E02144"
  .name_jp              #   "トヨタ自動車株式会社"
  .name_en              #   "TOYOTA MOTOR CORPORATION" or None
  .securities_code      #   "7203" or None

result.metadata         # FilingMetadata
  .doc_id               #   "S100ABCD"
  .fiscal_year          #   2024
  .period_start         #   date(2024, 4, 1)
  .period_end           #   date(2025, 3, 31)
  .accounting_standard  #   "JP-GAAP" | "IFRS" | "US-GAAP"
  .filing_type          #   "annual"

result.financials       # list[FinancialValue]
  [0].field_name        #   "revenue"
  [0].value             #   37154298000000 (integer JPY)
  [0].currency          #   "JPY"
  [0].context_ref       #   "CurrentYearDuration_ConsolidatedMember"
  [0].is_per_share      #   False
  [0].decimals          #   -6

result.raw_elements     # dict[str, str] — all unmatched XBRL elements
result.parse_warnings   # list[str] — non-fatal issues encountered
```

Per-share values (`eps`, `diluted_eps`, `bps`, `dividends_per_share`) are stored in 1/100 yen (sen). An EPS of ¥123.45 is stored as `12345`.

## Extracted fields

### Financials

| Field | JP-GAAP | IFRS | US-GAAP |
|-------|---------|------|---------|
| `revenue` | 売上高 (net sales) | 売上収益 (revenue) | Revenues |
| `operating_income` | 営業利益 | Operating profit | Operating income |
| `ordinary_income` | 経常利益 | — | — |
| `net_income` | Net income to owners | Profit to owners | Net income to parent |
| `total_assets` | 総資産額 | Assets | Assets |
| `net_assets` | 純資産額 | Equity | Stockholders' equity |
| `total_liabilities` | 負債 | Liabilities | Liabilities |

### Cash flow

| Field | Description |
|-------|-------------|
| `operating_cf` | Cash flows from operating activities |
| `investing_cf` | Cash flows from investing activities |
| `financing_cf` | Cash flows from financing activities |
| `cash_and_equivalents` | Cash and cash equivalents balance |

### Per-share (1/100 yen)

| Field | Description |
|-------|-------------|
| `eps` | Basic earnings per share |
| `diluted_eps` | Diluted earnings per share |
| `bps` | Book value per share |
| `dividends_per_share` | Dividend per share |

### Ratios and other

| Field | Description |
|-------|-------------|
| `equity_ratio` | Equity to asset ratio |
| `roe` | Return on equity |
| `pe_ratio` | Price earnings ratio |
| `payout_ratio` | Dividend payout ratio |
| `num_employees` | Number of employees |
| `capital_stock` | Capital stock |

### Debt breakdown

| Field | Description |
|-------|-------------|
| `short_term_loans` | Short-term loans payable |
| `long_term_loans` | Long-term loans payable |
| `bonds_payable` | Bonds payable |
| `current_portion_lt_loans` | Current portion of long-term loans |
| `commercial_paper` | Commercial paper |

## Limitations

This parser handles the common cases well — annual reports (有報) for most listed companies. But EDINET filings are messy:

- **Quarterly filings** (140) have different context structures; some fields won't resolve correctly
- **Amended filings** (訂正報告書) aren't distinguished from originals
- **Non-standard XBRL** — a handful of companies file with unusual namespace layouts or custom extensions that the taxonomy doesn't cover
- **Historical filings** before ~2019 sometimes use older taxonomy versions with different element IDs
- **No entity mapping** — you get EDINET codes and securities codes, but no ISIN, LEI, or cross-referencing

For production use across 4,000+ companies and 10 years of history, you'd need to handle these edge cases, run a pipeline, normalize across standards, and keep the taxonomy up to date.

## Don't want to run the parser yourself?

[Axiora](https://axiora.dev) is a hosted API for structured Japanese financial data — 4,125 companies, 10 years of history, English translations, entity mapping, all served as JSON. The parser runs so you don't have to.

Read more: [EDINET for Developers: The Complete English Guide](https://axiora.dev/en/blog/edinet-for-developers)

## License

Modified MIT — see [LICENSE](LICENSE).
