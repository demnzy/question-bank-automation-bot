# QB Automation Bot — v1

> Automated pipeline for transforming raw exam PDFs into precise, LMS-ready question bank schemas — covering **Multiple Choice (MCQ)** and **True/False** question types.

**Stack:** Python · PyMuPDF (fitz) · GitHub Actions · n8n

---

## Table of Contents

- [Overview](#overview)
- [How It Works](#how-it-works)
- [Question Types Supported](#question-types-supported)
- [Repository Structure](#repository-structure)
- [Setup](#setup)
  - [Secrets & Environment Variables](#secrets--environment-variables)
  - [Triggering the Workflow](#triggering-the-workflow)
- [Output Schema](#output-schema)
- [Local Development](#local-development)
- [Upgrading](#upgrading)

---

## Overview

QB Bot v1 solves a specific, painful problem: exam PDFs are dense, inconsistently formatted, and completely useless to an LMS without structured transformation. This pipeline takes those raw PDFs, extracts and classifies every question using Python and PyMuPDF, and outputs a clean JSON schema that can be consumed directly by the LMS (succeedquiz.com) or any downstream system.

The entire process is automated. n8n triggers the GitHub Actions workflow, the Python transformer runs inside the Action, and the output is pushed to a storage target without any manual intervention.

---

## How It Works

```
n8n Workflow
    │
    │  Webhook trigger (POST with PDF reference or payload)
    ▼
GitHub Actions (workflow_dispatch or repository_dispatch)
    │
    ├── Checkout repo
    ├── Set up Python environment
    ├── Install dependencies
    ├── Run transform.py
    │       │
    │       ├── Load PDF with PyMuPDF (fitz)
    │       ├── Extract raw text page by page
    │       ├── Detect and classify question blocks
    │       │     ├── Multiple Choice — identifies stem, options A–D, correct answer
    │       │     └── True/False — identifies statement and boolean answer
    │       ├── Validate against output schema
    │       └── Write structured JSON output
    │
    └── Push output JSON to repo / storage bucket
            │
            ▼
        n8n picks up output and routes to LMS API
```

---

## Question Types Supported

| Type | Detection Method | Output Fields |
|---|---|---|
| Multiple Choice (MCQ) | Option labels A–D in proximity to stem | `stem`, `options[]`, `correct_answer`, `explanation` |
| True / False | Boolean keywords after statement | `statement`, `correct_answer` (`true`/`false`), `explanation` |

---

## Repository Structure

```
qb-bot-v1/
│
├── .github/
│   └── workflows/
│       └── transform.yml        # GitHub Actions workflow definition
│
├── scripts/
│   └── transform.py             # Core PDF extraction and schema builder
│
├── schemas/
│   └── question_schema_v1.json  # Reference schema for output validation
│
├── input/                       # PDFs dropped here for local runs
│   └── .gitkeep
│
├── output/                      # Transformed JSON written here
│   └── .gitkeep
│
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### Secrets & Environment Variables

Add the following secrets to your GitHub repository under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `N8N_WEBHOOK_URL` | The n8n webhook URL to notify on completion |
| `STORAGE_BUCKET_URL` | Target storage URL for output JSON (if using external bucket) |
| `STORAGE_ACCESS_KEY` | Access credentials for the storage target |

For local development, copy `.env.example` to `.env` and fill in values:

```env
N8N_WEBHOOK_URL=https://your-n8n-instance/webhook/qb-bot
STORAGE_BUCKET_URL=https://your-bucket-url
STORAGE_ACCESS_KEY=your-access-key
```

### Triggering the Workflow

**From n8n:**

Use the `HTTP Request` node in your n8n workflow to send a `repository_dispatch` event to GitHub:

```
POST https://api.github.com/repos/{owner}/qb-bot-v1/dispatches

Headers:
  Authorization: Bearer <GITHUB_PAT>
  Accept: application/vnd.github.v3+json

Body:
{
  "event_type": "transform-pdf",
  "client_payload": {
    "pdf_url": "https://link-to-your-pdf.pdf",
    "exam_id": "exam_001"
  }
}
```

**Manually (GitHub UI):**

Go to **Actions → Transform PDF → Run workflow** and provide the required inputs.

**From the CLI:**

```bash
gh workflow run transform.yml \
  -f pdf_url="https://link-to-your-pdf.pdf" \
  -f exam_id="exam_001"
```

---

## Output Schema

Every question extracted is written to a JSON array conforming to this structure:

```json
[
  {
    "type": "mcq",
    "exam_id": "exam_001",
    "question_number": 1,
    "stem": "Which of the following best describes photosynthesis?",
    "options": {
      "A": "The breakdown of glucose to release energy",
      "B": "The conversion of light energy into chemical energy",
      "C": "The transport of water through a plant",
      "D": "The absorption of minerals from the soil"
    },
    "correct_answer": "B",
    "explanation": ""
  },
  {
    "type": "true_false",
    "exam_id": "exam_001",
    "question_number": 2,
    "statement": "The mitochondria is the powerhouse of the cell.",
    "correct_answer": true,
    "explanation": ""
  }
]
```

Output files are named `{exam_id}_transformed.json` and written to the `output/` directory before being pushed to the configured storage target.

---

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/demnzy/qb-bot-v1.git
cd qb-bot-v1

# 2. Set up a virtual environment
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Drop a PDF into input/
cp your-exam.pdf input/

# 5. Run the transformer locally
python scripts/transform.py --input input/your-exam.pdf --exam_id exam_001

# Output will appear in output/exam_001_transformed.json
```

---

## Upgrading

For extended question type support — fill in the gaps, hotspot simulations, matching, and more — see [QB Automation Bot v2](https://github.com/demnzy/qb-bot-v2), which builds directly on this pipeline.

---

Built by [Oluwatobiloba (Daniel) Davies](https://github.com/demnzy) · [LinkedIn](https://linkedin.com/in/oluwatobiloba-davies)
