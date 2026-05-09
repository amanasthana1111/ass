# Fact-Check Agent 🔍

> **Automated PDF Fact-Checking with Gemini LLM**
> 
> Verify claims in PDFs against live web evidence using semantic analysis powered by Google Gemini 2.5 Flash.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Verdict Definitions](#verdict-definitions)
- [Limitations & Future Work](#limitations--future-work)

---

## 📌 Overview

**Fact-Check Agent** is a lightweight, web-based fact-checking system designed to verify claims in marketing documents, reports, pitch decks, and other PDFs.

### The Problem
Marketing and business documents often contain:
- **Outdated statistics** ("We have 10 million users" - from 2022)
- **Unsupported claims** (numbers with no reliable source)
- **Hallucinated data** (fabricated or inflated metrics)

### The Solution
Upload a PDF → Extract claims → Search live web evidence → Compare → Generate verified report

---

## ✨ Key Features

### 📄 PDF Processing
- Extract claims from up to 25 pages
- Identify claim types: financial, statistics, dates, technical specs, figures
- Support for selectable text PDFs (OCR not included)

### 🔎 Intelligent Claim Extraction
- Automatically identifies claims containing:
  - Financial figures ($, revenue, valuation)
  - Statistics (%, growth rates)
  - Dates (years, quarters, launch dates)
  - Technical specs (bandwidth, capacity)
  - Quantifiable metrics (users, employees, downloads)

### 🌐 Live Web Verification
- Search live web for corroborating evidence
- Dual search integration:
  - **Tavily Search API** (primary - more reliable)
  - **DuckDuckGo** (fallback - always available)

### 🤖 Semantic Analysis
- Uses **Google Gemini 2.5 Flash** for intelligent fact verification
- Compares claim semantics against evidence semantics
- Generates structured JSON verdicts with confidence levels

### 📊 Comprehensive Reporting
- Claim-by-claim verdict breakdown
- Evidence links and snippets for transparency
- Confidence levels (High/Medium/Low)
- CSV export for integration with other tools
- JSON API for programmatic access

---

## 🛠 Technology Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.11 |
| **Web Framework** | Streamlit (frontend) / FastAPI-compatible (API) |
| **PDF Processing** | pypdf 5.0.1 |
| **Web Scraping** | BeautifulSoup4 4.12.3 |
| **HTTP Client** | Requests 2.32.3 |
| **LLM** | Google Gemini 2.5 Flash |
| **Search** | Tavily Search API + DuckDuckGo |
| **Deployment** | Vercel, Streamlit Cloud, or Render |

### ⚠️ Important: Gemini Only, No OpenAI
- **NO OpenAI dependencies**
- **ONLY Google Gemini LLM** is used
- Model: `gemini-2.5-flash`
- Temperature: 0 (deterministic)
- Structured JSON output

---

## 📁 Project Structure

```
fact-check-agent/
├── app.py                      # Main Streamlit web application
├── factcheck_core.py           # Core fact-checking logic
├── api/
│   └── factcheck.py           # Vercel serverless API endpoint
├── public/
│   └── index.html             # Frontend HTML interface
├── requirements.txt            # Core Python dependencies
├── requirements-streamlit.txt   # Streamlit-specific dependencies
├── vercel.json                # Vercel deployment configuration
├── render.yaml                # Render deployment configuration
├── Procfile                   # Web process file
├── runtime.txt                # Python 3.11.9
├── .gitignore                 # Git ignore rules
├── .streamlit/
│   └── config.toml            # Streamlit configuration
└── README.md                  # This file
```

### Key Files Explained

| File | Purpose |
|------|---------|
| `factcheck_core.py` | Core extraction, search, LLM integration |
| `app.py` | Streamlit UI with upload, results, CSV export |
| `api/factcheck.py` | Vercel serverless API (multipart form handler) |
| `public/index.html` | Standalone frontend (works with API) |

---

## 🔄 How It Works

### Step 1: PDF Text Extraction
```
User uploads PDF
    ↓
pypdf extracts text from up to 25 pages
    ↓
Sentences are normalized and split
```

### Step 2: Claim Extraction
```
For each sentence:
  - Extract numeric values (%, $, dates, specs)
  - Classify type (financial, statistic, date, technical, figure)
  - Build search query from keywords + values
    ↓
Max 24 claims returned
```

### Step 3: Web Evidence Search
```
For each claim:
  - Generate search query
  - Try Tavily API (if TAVILY_API_KEY set)
  - Fallback to DuckDuckGo
  - Return up to 6 results
```

### Step 4: Semantic Verification
```
For each claim + evidence pair:
  
  If GEMINI_API_KEY is set:
    → Use Gemini 2.5 Flash to analyze semantic entailment
    → Returns structured verdict (Verified/Inaccurate/False)
    → Includes confidence and reasoning
  
  Else:
    → Use deterministic heuristics:
      - Pattern matching (FIFA World Cup, founded in, acquired)
      - Value matching with tolerance
      - Keyword overlap scoring
    → Returns fallback verdict
```

### Step 5: Report Generation
```
Results aggregated with:
  - Verdict counts
  - Claim-by-claim details
  - Evidence links
  - Corrected facts (when available)
    ↓
Output as: Streamlit UI + CSV + JSON
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- pip or poetry
- (Optional) Gemini API key for semantic verification
- (Optional) Tavily API key for better search

### Installation

#### Option 1: Streamlit Web App (Easiest)
```bash
# Clone or download the repository
cd fact-check-agent

# Install dependencies
pip install -r requirements-streamlit.txt

# Run the app
streamlit run app.py
```

The app will open at `http://localhost:8501`

#### Option 2: API Only (Vercel)
```bash
# Install core dependencies
pip install -r requirements.txt

# (Optional) Test locally with Vercel CLI
npm install -g vercel
vercel dev
```

Local API will be at `http://localhost:3000`

#### Option 3: Docker (Coming Soon)
Docker support not yet implemented. Use pip installation above.

---

## ⚙️ Configuration

### Environment Variables

#### Required for LLM-based Verification
```bash
GEMINI_API_KEY=<your-gemini-api-key>
FACTCHECK_LLM_PROVIDER=gemini
```

#### Optional for Enhanced Search
```bash
TAVILY_API_KEY=<your-tavily-api-key>
```

#### Optional Tuning
```bash
GEMINI_MAX_TOKENS=1600          # Max LLM response tokens
GEMINI_TIMEOUT=35               # LLM request timeout (seconds)
GEMINI_MAX_RETRIES=2            # Retry failed LLM calls
FACTCHECK_MAX_WORKERS=1         # Parallel claim workers (1 with LLM, 4+ without)
```

### Streamlit Secrets (Cloud Deployment)

On Streamlit Cloud, add secrets via UI or `.streamlit/secrets.toml`:
```toml
GEMINI_API_KEY = "your-gemini-api-key"
FACTCHECK_LLM_PROVIDER = "gemini"
GEMINI_MAX_TOKENS = "1600"
FACTCHECK_MAX_WORKERS = "1"
TAVILY_API_KEY = "your-tavily-api-key"
```

---

## 🌍 Deployment

### Option 1: Vercel (Recommended for API)

#### Prerequisites
- Vercel account
- GitHub repository connected to Vercel

#### Steps
1. Push code to GitHub
2. Connect repo to Vercel
3. Set environment variables in Vercel dashboard:
   - `GEMINI_API_KEY`
   - `FACTCHECK_LLM_PROVIDER=gemini`
   - `TAVILY_API_KEY` (optional)
4. Deploy: `vercel --prod`

#### Test Deployment
```bash
curl -X POST https://your-project.vercel.app/api/factcheck \
  -F "pdf=@document.pdf"
```

---

### Option 2: Streamlit Cloud (Easiest)

#### Steps
1. Push code to GitHub
2. Go to [https://share.streamlit.io/](https://share.streamlit.io/)
3. Click "New app"
4. Select repository and set main file to `app.py`
5. Add secrets via dashboard
6. Deploy

Your app will be live at `https://share.streamlit.io/your-username/your-repo/app.py`

---

### Option 3: Render (Free Tier Available)

#### Steps
1. Push code to GitHub
2. Go to [https://render.com](https://render.com)
3. Create new Web Service
4. Connect GitHub repo
5. Build command: `pip install -r requirements-streamlit.txt`
6. Start command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
7. Add environment variables
8. Deploy

---

## 📡 API Reference

### POST `/api/factcheck`

**Purpose:** Fact-check a PDF document

**Request:**
- **Method:** POST
- **Content-Type:** multipart/form-data
- **Parameter:** `pdf` (file)

**Example:**
```bash
curl -X POST https://your-app.vercel.app/api/factcheck \
  -F "pdf=@marketing_deck.pdf"
```

**Response:**
```json
{
  "claims": [
    {
      "id": 1,
      "text": "The company has 50 million users.",
      "kind": "figure",
      "page": 2,
      "values": ["50 million"]
    }
  ],
  "results": [
    {
      "id": 1,
      "verdict": "Inaccurate",
      "confidence": "Medium",
      "claim": "The company has 50 million users.",
      "reason": "Web evidence shows the company reported 42 million users in Q4 2024.",
      "correct_fact": "The company has 42 million users (Q4 2024).",
      "sources": [
        {
          "title": "Company Q4 2024 Earnings Report",
          "url": "https://example.com/earnings",
          "snippet": "...reported 42 million users...",
          "source": "example.com"
        }
      ]
    }
  ],
  "counts": {
    "Verified": 8,
    "Inaccurate": 3,
    "False": 2
  }
}
```

---

## 📊 Verdict Definitions

| Verdict | Meaning | Example |
|---------|---------|---------|
| **Verified** | PDF claim matches web evidence semantically | PDF: "Founded in 1998" ✓ Web: "Google was founded in 1998" |
| **Inaccurate** | Related evidence exists but values don't match | PDF: "Founded in 2000" ✗ Web: "Founded in 1998" |
| **False** | No web evidence supports the claim | PDF: "We have 500M users" - No reliable source found |

### Confidence Levels
- **High:** Strong semantic match or direct value match
- **Medium:** Related evidence with minor discrepancies
- **Low:** Limited evidence or uncertain match

---

## 🎯 Example Workflow

### Input PDF Contains:
```
"TechCorp generated $5 billion in revenue in 2024."
"The market grew 45% year-over-year."
"We serve 2 million customers worldwide."
```

### App Extracts:
```
✓ Claim 1: Financial - "$5 billion in revenue in 2024"
✓ Claim 2: Statistic - "45% year-over-year growth"
✓ Claim 3: Figure - "2 million customers"
```

### Web Search Finds:
```
Claim 1 Evidence:
  - TechCorp Q4 2024: "$4.8 billion annual revenue"
  → Verdict: INACCURATE (close but not exact)

Claim 2 Evidence:
  - Industry reports: "Tech sector grew 47% in 2024"
  → Verdict: INACCURATE (sector ≠ company)

Claim 3 Evidence:
  - Latest press release: "2M+ customers served"
  → Verdict: VERIFIED
```

### Output Report:
```csv
verdict,claim,confidence,reason,correct_fact
Inaccurate,"$5B revenue",Medium,"Web shows $4.8B for 2024","TechCorp reported $4.8B revenue in 2024"
Inaccurate,"45% growth",Low,"Industry grew 47%, not company-specific","Tech sector grew 47% in 2024"
Verified,"2M customers",High,"Confirmed by press release","TechCorp serves 2M+ customers"
```

---

## ⚠️ Limitations & Future Work

### Current Limitations
- ❌ **No OCR:** Scanned image-only PDFs not supported
- ⚠️ **Search Quality:** Limited by free search APIs (Tavily/DuckDuckGo)
- ⏱️ **Timeout:** 35-second max per claim (Gemini API limit)
- 📄 **Snippet Only:** Analysis based on search snippets, not full pages
- 🎯 **Ambiguous Claims:** High-complexity claims may be marked FALSE

### Recommended Enhancements
1. **Add OCR** - Tesseract or Google Cloud Vision
2. **Full Page Parsing** - Fetch and analyze source pages
3. **Source Ranking** - Prefer official/government sources
4. **Citation Tracking** - Maintain evidence chains
5. **Report History** - Store and compare past checks
6. **Batch Processing** - Queue large document sets
7. **Custom Models** - Fine-tune LLM on domain-specific data

---

## 📝 Example Verdicts

### ✅ Verified
```json
{
  "verdict": "Verified",
  "claim": "Microsoft acquired LinkedIn in 2016.",
  "reason": "Web evidence confirms Microsoft acquired LinkedIn in 2016.",
  "sources": ["linkedin.com", "microsoft.com"]
}
```

### ⚠️ Inaccurate
```json
{
  "verdict": "Inaccurate",
  "claim": "Google was founded in 2015.",
  "reason": "Evidence shows Google was founded in 1998, not 2015.",
  "correct_fact": "Google was founded in 1998."
}
```

### ❌ False
```json
{
  "verdict": "False",
  "claim": "India won FIFA World Cup 2022.",
  "reason": "Evidence contradicts: Argentina won FIFA World Cup 2022.",
  "correct_fact": "Argentina won FIFA World Cup 2022."
}
```

---

## 📞 Support & Contributions

### Issues & Bugs
Found a bug? Please file an issue on GitHub with:
- PDF that triggered the issue
- Expected vs actual verdict
- Environment details (OS, Python version)

### Contributing
Contributions welcome! Areas:
- OCR integration
- Additional search providers
- Better extraction patterns
- UI/UX improvements

### Questions?
Check the [Limitations](#limitations--future-work) section first, then file an issue.

---

## 📄 License

This project is provided as-is for educational and assignment purposes.

---

## 🔗 Resources

- [Google Gemini API Docs](https://ai.google.dev/)
- [Streamlit Documentation](https://docs.streamlit.io/)
- [Vercel Deployment Guide](https://vercel.com/docs)
- [pypdf Documentation](https://pypdf.readthedocs.io/)

---

**Last Updated:** May 9, 2026
**Python Version:** 3.11+
**LLM Model:** Gemini 2.5 Flash (Google)
**Status:** ✅ Production Ready
