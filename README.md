# Question Bank Automation Bot (v1)

Turns the messy, LLM-extracted output of exam-dump PDFs into a clean, relational workbook that can be imported into an LMS ([succeedquiz.com](https://succeedquiz.com)). It also finds the figure belonging to each image-based question in the source PDF, crops it, uploads it, and stores the resulting URL in the question's media column.

v1 covers **option-based text questions**: multiple choice, multiple answer and true/false. Hotspot, drag-and-drop and simulation rows are deliberately skipped here and handled by [v2](https://github.com/demnzy/question-bank-automation-bot-v2).

**Stack:** Python 3.9, pandas, openpyxl, PyMuPDF, GitHub Actions, n8n

## Why this exists

Exam dumps arrive as long PDFs. An LLM can extract the questions, but its output is inconsistent: literal `null` strings, questions repeated where chunks overlap, rows with missing options, free-form option and answer formatting. The LMS import template expects five linked sheets with stable keys. This repo is the step that sits between the two.

## Pipeline

```
n8n workflow A
  LLM extraction of the PDF -> Excel table (14 columns)
  uploads Excel + PDF, then sends a repository_dispatch event
        |
        v
GitHub Actions (.github/workflows/process_exam.yml)
  1. download the Excel and PDF from the payload URLs
  2. image_miner.py            -> image_lookup.json   {question text: image URL}
  3. main_az104_adapter.py     -> <exam>_Final.xlsx   (5 sheets, template columns)
  4. POST the workbook to the n8n callback URL
        |
        v
n8n workflow B
  receives the file together with folder_id and user_email
```

## Input

An Excel (`.xlsx`/`.xls`), CSV or JSON file with these 14 columns. For Excel, the sheet named `Extraction Template` is used if present, otherwise the first sheet. Column names are matched case- and punctuation-insensitively (for example `Correct Answer` and `Answers` are accepted for `Correct Options`).

| Column | Notes |
|---|---|
| `Question` | May contain `<<IMAGE_REF_n>>` tags, which are ignored when locating text in the PDF |
| `Options` | `A) text; B) text; C) text` (separator `;` or `\|`) |
| `Question_Type` | `multiple_choice`, `multiple_answer`, `true_false`. Inferred from the options if blank |
| `has_image` | `true`/`1`/`yes` marks questions that need a figure |
| `Correct Options` | `B) text` for single answer, `A) text; C) text` for multiple answer |
| `Explanation`, `Hints` | A leading `Hint:` prefix and trailing `[abc123]` markers are stripped from hints |
| `Category`, `Collection`, `Quiz` | Defaults below apply when blank |
| `Tag`, `difficulty`, `isPublic`, `Status` | `difficulty` must be `low`/`medium`/`high`, otherwise `medium`. `Status` is always set to `draft` |

Example row:

| Question | Options | Correct Options |
|---|---|---|
| Which service stores secrets and keys? | A) Key Vault; B) Load Balancer; C) Bastion; D) Front Door | A) Key Vault |

## What the adapter does

`main_az104_adapter.py` runs these steps in order:

1. **Normalise columns** to the 14-column schema, adding any that are missing.
2. **Remove `null` strings** left by the LLM.
3. **Deduplicate** questions repeated by overlapping chunks, by hashing lower-cased alphanumeric text (MD5) and keeping the first occurrence.
4. **Drop rows with no options**, which are treated as hallucinated items.
5. **Skip** rows whose type contains `hotspot`, `drag` or `simulation`.
6. **Fill defaults**, and where `Quiz` is blank, assign questions to `Batch 1`, `Batch 2`, ... in groups of 45.
7. **Build the five sheets** with deterministic keys (`CAT-...`, `COL-...`, `QUIZ-...`, `Q-<quiz>-001`, `OPT-<question>-01`).
8. **Parse answers** into per-option `IsCorrect` flags.
9. **Infer quiz tags** from the collection name, the exam code in the quiz title (such as `AZ-104`), and a keyword map over question and explanation text. Quiz difficulty is the most common question difficulty (ties give `medium`).
10. **Attach images** (see below).

### Output

`<exam>_Final.xlsx` with sheets `Categories`, `Collections`, `Quizzes`, `Questions`, `Options`. Column names and order are read from `SQ_template.xlsx`: columns the code produces but the template lacks are dropped, and template columns the code does not fill are left empty.

Fixed values: `Points = 1`, `PassMark = 70`, `Status = draft`, `isPublic = true`.

### Image handling

`image_miner.py` handles each row where `has_image` is true:

1. Search the PDF for the first 80 characters of the question text (then the first 40) and take the first page where it is found.
2. Crop the full page width from just below the match, 350 pt tall (or to the page bottom), rendered at 200 dpi as JPEG.
3. Log in to the LMS API, upload the crop, and record `{question text: image URL}` in `image_lookup.json`.

In the adapter, a question whose text is in the lookup gets that URL in `MediaURL`. If it is flagged `has_image` but has no URL, `MediaURL` is set to `1`, which marks it for manual follow-up. The miner prints a summary of successes and failures.

## Running it

### Through GitHub Actions

The workflow triggers on a `repository_dispatch` event of type `start-processing`:

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/demnzy/question-bank-automation-bot/dispatches \
  -d '{
    "event_type": "start-processing",
    "client_payload": {
      "collection_name": "AZ-104",
      "excel_url": "https://example.com/extracted.xlsx",
      "pdf_url": "https://example.com/exam.pdf",
      "callback_url": "https://your-n8n-host/webhook/final",
      "folder_id": "FOLDER_ID",
      "user_email": "user@example.com"
    }
  }'
```

| Payload key | Used for |
|---|---|
| `collection_name` | Sanitised into the file names (`<name>.xlsx`, `<name>_Final.xlsx`) |
| `excel_url`, `pdf_url` | Inputs to download |
| `callback_url` | Where the finished workbook is POSTed (http is upgraded to https) |
| `folder_id`, `user_email` | Passed through to n8n workflow B unchanged |

**Repository secrets** (Settings, then Secrets and variables, then Actions):

| Secret | Description |
|---|---|
| `SUCCEED_EMAIL` | LMS account used to upload images |
| `SUCCEED_PASSWORD` | Password for that account |

The scripts read these from environment variables. Never commit credentials to the repository.

### Locally

```bash
pip install -r requirements.txt
export SUCCEED_EMAIL="..." SUCCEED_PASSWORD="..."

python image_miner.py exam.xlsx exam.pdf image_lookup.json
python main_az104_adapter.py \
  --input exam.xlsx \
  --template SQ_template.xlsx \
  --output exam_Final.xlsx \
  --lookup image_lookup.json
```

`--lookup` is optional. Without it, flagged questions get the `1` placeholder in `MediaURL`.

## Configuration

Defaults are constants at the top of `main_az104_adapter.py`, and are tuned for Microsoft Azure exams (AZ-104):

- `DEFAULT_CATEGORY_NAME = "MICROSOFT"`, `DEFAULT_COLLECTION_NAME = "Microsoft Azure"`
- `DEFAULT_PASSMARK`, `DEFAULT_POINTS`
- `KEYWORD_TAG_MAP` (Azure service keywords to tags) and `learning_outcome_for()`

For other exams, edit those. The LMS API endpoints are constants at the top of `image_miner.py`.

## Known limitations

- Image cropping is geometric: it assumes the figure sits directly below the question text and fits in a 350 pt band. Figures that sit elsewhere, or questions whose text cannot be found verbatim in the PDF, fall back to the `1` placeholder.
- Options with no text (`Options` empty) are dropped before type handling, so open-ended questions do not pass through v1.
- Tag inference is a keyword map and only recognises the listed Azure topics.
- The workbook is only as good as the LLM extraction feeding it; the adapter normalises and filters but does not verify answers.

## Repository layout

```
.github/workflows/process_exam.yml   Actions workflow (repository_dispatch)
image_miner.py                       find, crop and upload question images
main_az104_adapter.py                normalise LLM output into the LMS workbook
SQ_template.xlsx                     LMS import template (sheet and column names)
requirements.txt
```

## Related

- [v2](https://github.com/demnzy/question-bank-automation-bot-v2): hotspot, drag-and-drop and scenario questions, and bounding-box image cropping.

Built by [Oluwatobiloba (Daniel) Davies](https://github.com/demnzy).
