# Claim Audit Desk

Claim Audit Desk is a lightweight PDF fact-checking tool. It extracts measurable claims from a PDF, searches the web for supporting evidence, and classifies each claim as `Verified`, `Inaccurate`, or `False`.

The project ships with two interfaces:

- A Streamlit app in `app.py` for interactive document audits.
- A Vercel-compatible JSON API in `api/factcheck.py` for programmatic PDF checks.

## Features

- Extracts selectable text from PDF files with `pypdf`.
- Scans up to 25 pages per upload.
- Extracts up to 5 checkable claims per document.
- Detects financial, statistic, date, technical, and figure-based claims.
- Searches live web evidence with Tavily when configured, then falls back to DuckDuckGo.
- Uses Gemini 2.5 Flash for semantic verification when `GEMINI_API_KEY` is available.
- Falls back to deterministic semantic checks when no LLM key is configured.
- Exports audit results as CSV and JSON from the Streamlit UI.
- Exposes a `POST /api/factcheck` endpoint for serverless deployments.

## Tech Stack

| Area | Technology |
| --- | --- |
| Language | Python 3.11 |
| UI | Streamlit |
| PDF parsing | pypdf |
| Web search | Tavily API, DuckDuckGo HTML fallback |
| HTML parsing | BeautifulSoup |
| HTTP client | requests |
| LLM verifier | Google Gemini 2.5 Flash |
| Serverless API | Vercel Python runtime |
| Tests | unittest |

## Project Structure

```text
.
|-- api/
|   `-- factcheck.py              # Vercel serverless API handler
|-- app.py                        # Streamlit web application
|-- factcheck_core.py             # PDF extraction, claim extraction, search, and verification logic
|-- test_semantic_verification.py # Unit tests for deterministic semantic checks
|-- requirements.txt              # Core API/runtime dependencies
|-- requirements-streamlit.txt    # Streamlit app dependencies
|-- vercel.json                   # Vercel routing/build configuration
|-- Procfile                      # Render/Heroku-style Streamlit start command
|-- runtime.txt                   # Python runtime version
|-- .gitignore                    # Ignored local/generated files
`-- README.md                     # Project documentation
```

## How It Works

1. The user uploads a PDF.
2. `extract_pdf_text` reads selectable text from the first 25 pages.
3. `extract_claims` splits text into sentences and keeps sentences with numeric, date, financial, or technical signals.
4. Each claim is converted into a web search query.
5. `search_web` tries Tavily first when `TAVILY_API_KEY` is set, then falls back to DuckDuckGo.
6. `infer_verdict` asks Gemini for semantic adjudication when available.
7. If Gemini is unavailable or fails, fallback checks handle a small set of deterministic contradiction and paraphrase cases.
8. The UI/API returns the verdict, confidence, reason, corrected fact, semantic details, and source links.

## Getting Started

### Prerequisites

- Python 3.11+
- pip
- Optional: `GEMINI_API_KEY` for LLM-based semantic verification
- Optional: `TAVILY_API_KEY` for stronger search results

### Run the Streamlit App

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-streamlit.txt
streamlit run app.py
```

Open the local Streamlit URL printed by the command, usually:

```text
http://localhost:8501
```

### Run Core Tests

```bash
python -m unittest test_semantic_verification.py
```

## Configuration

Environment variables are optional, but strongly recommended for production-quality verification.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | No | unset | Enables Gemini semantic verification. |
| `TAVILY_API_KEY` | No | unset | Enables Tavily search before DuckDuckGo fallback. |
| `GEMINI_MAX_TOKENS` | No | `1600` | Maximum Gemini response tokens. |
| `FACTCHECK_MAX_WORKERS` | No | `1` with LLM, `4` without LLM | Controls verification concurrency. |

The application is intentionally locked to Gemini through `configured_provider()` in `factcheck_core.py`.

## Streamlit Usage

1. Start the app with `streamlit run app.py`.
2. Upload a text-based PDF.
3. Review extracted claims in the table.
4. Click `Start Claim Audit`.
5. Inspect verdict cards, source snippets, semantic analysis, and corrected facts.
6. Download the CSV report when needed.

Scanned image-only PDFs are not supported because OCR is not implemented.

## API Usage

The API expects a multipart form upload with a file field named `pdf`.

```bash
curl -X POST https://your-deployment.example/api/factcheck \
  -F "pdf=@document.pdf"
```

Example response shape:

```json
{
  "claims": [
    {
      "id": 1,
      "text": "Microsoft acquired LinkedIn in 2016.",
      "kind": "date",
      "page": 1,
      "query": "Microsoft acquired LinkedIn 2016 official source latest",
      "values": ["2016"]
    }
  ],
  "results": [
    {
      "id": 1,
      "page": 1,
      "claim": "Microsoft acquired LinkedIn in 2016.",
      "type": "date",
      "verdict": "Verified",
      "confidence": "Medium",
      "semantic_relation": "entails",
      "reason": "The evidence states the same acquisition relationship and year.",
      "correct_fact": "Microsoft acquired LinkedIn in 2016.",
      "sources": []
    }
  ],
  "counts": {
    "Verified": 1,
    "Inaccurate": 0,
    "False": 0
  }
}
```

## Deployment

### Streamlit-Compatible Hosts

Use these commands:

```bash
pip install -r requirements-streamlit.txt
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

The included `Procfile` already contains this start command.

### Vercel API

The repository includes `vercel.json` for the Python API route at `/api/factcheck`.

Important: the current `vercel.json` also routes non-API traffic to `/public/index.html`. If you deploy the Vercel frontend route, add that file or adjust the catch-all route. The API route itself is implemented in `api/factcheck.py`.

## Verdicts

| Verdict | Meaning |
| --- | --- |
| `Verified` | Evidence semantically supports the full claim. |
| `Inaccurate` | Evidence is related, but the claim is materially wrong, outdated, incomplete, or imprecise. |
| `False` | Evidence contradicts the claim or does not support it. |

Confidence values are `High`, `Medium`, or `Low`.

## Limitations

- No OCR for scanned PDFs.
- Search quality depends on Tavily/DuckDuckGo result quality.
- Verification uses search snippets, not full source-page extraction.
- The fallback verifier is intentionally conservative and only handles limited deterministic patterns.
- The API and UI perform live network calls during audits, so runtime depends on search and LLM latency.

## License

This project is provided as-is for educational and assignment use.
