# TokenCraft — by IndexCraft

A dashboard that converts files to Markdown and tells you **honestly** whether
that conversion actually saved tokens for your use case — instead of
claiming a flat "5-10x savings" regardless of what you upload.

Built on [Microsoft's `markitdown`](https://github.com/microsoft/markitdown)
as the conversion engine, with a FastAPI dashboard on top: bulk upload,
live per-file token comparisons, a chart, and one-click export — either
running locally on your own machine, or deployed as a hosted web app.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688)
![License](https://img.shields.io/badge/license-MIT-green)

## Why this exists

Most "convert to Markdown for AI" tools quote a single flat token-savings
number. In practice it depends entirely on the source file:

- A **scanned or image-heavy PDF** genuinely saves a lot — an LLM reads it
  page-by-page as an image (often 1,000+ tokens/page) unless you convert it
  first.
- A **plain text PDF** (a resume, a letter) saves close to nothing — it's
  already read as clean text, so converting it adds little benefit and can
  even add slight overhead.
- Formats like **.docx or .html** are already read as text natively — there's
  no "as an image" baseline to compare against at all, so a savings
  multiplier for them is meaningless.

TokenCraft measures this per file — using a real tokenizer (`tiktoken`) and
Anthropic's published image-token formula against the file's actual PDF page
dimensions — instead of assuming or fabricating a number. If there's no
valid baseline for a format, it says so, rather than making one up.

## Two deployment modes, one codebase

| | Local (`run.bat` / `run.sh`) | Hosted (Wasmer or any server) |
|---|---|---|
| Folder browse / save / open-in-explorer | ✅ enabled | ❌ disabled — a hosted server has no business touching a visitor's filesystem |
| Download individual / zip | ✅ | ✅ |
| Token analysis, chart, everything else | ✅ | ✅ |

Controlled by one environment variable, `TOKENCRAFT_LOCAL_MODE` — no
duplicated code between the two.

## Setup — run locally

```bash
git clone https://github.com/indexcraft/tokencraft.git
cd tokencraft
pip install -r requirements.txt
```

**One-click:** double-click `run.bat` (Windows) or run `./run.sh`
(Mac/Linux) — installs dependencies if missing and opens your browser at
`http://127.0.0.1:8000` automatically.

**Manual:**

```bash
uvicorn app:app --reload
```

If you want AI-vision OCR for scanned pages/images (optional, brings your
own OpenAI key, used only for that request):

```bash
pip install openai
```

## Deploy to Wasmer

Wasmer auto-detects Python web apps from `requirements.txt` + an ASGI
`app` object in `app.py` — no Dockerfile needed for the standard path.

```bash
wasmer login
wasmer deploy
```

Edit `app.yaml` first and replace `<your-wasmer-username>` with your actual
namespace. `TOKENCRAFT_LOCAL_MODE` is already set to `false` in there, which
disables the local-filesystem endpoints for the hosted deployment.

**Honesty note on this path:** `pymupdf` (used for PDF page-image token
analysis) is a native C extension wrapping the MuPDF library. As of writing,
Wasmer's WASIX Python runtime's compatibility with heavy native extensions
is still maturing — I haven't been able to verify a live deployment myself.
The code is defensive about this: `token_utils.py` catches the import
failure and simply drops the native-token comparison for PDFs (everything
else — conversion, downloads, the rest of the dashboard — keeps working).
If `pymupdf` fails to install on Wasmer, remove it from `requirements.txt`
and PDF conversions will still work; you'll just lose the "native vs
converted" comparison for that format specifically. Test your own
deployment before relying on it.

## Why this is better than plain `markitdown`

`markitdown` itself is a solid conversion library — TokenCraft doesn't
replace it, it wraps it. What TokenCraft adds:

- **A dashboard**, instead of a Python API you have to script yourself —
  bulk upload, live preview, one-click export.
- **Honest, per-file token math** — real `tiktoken` counts and Anthropic's
  published image-token formula against actual PDF page dimensions, not a
  flat marketing multiplier. Every number is computed live from the file you
  uploaded; nothing is `random.uniform()`'d to look plausible.
- **A density check for PDFs** — flags whether a PDF is text-based or
  image-heavy *before* you commit to converting it, so you're not guessing.
- **Format-aware honesty** — for formats with no meaningful "native upload"
  baseline (`.docx`, `.html`, `.csv`...), TokenCraft says so explicitly
  instead of inventing a ratio.
- **Two ready deployment paths** — run it locally with full filesystem
  integration, or host it, from the same code.

## A note on parallel conversion

Conversion is intentionally **sequential**, not multi-threaded or
multi-processed. This was tested, not assumed: `ThreadPoolExecutor` and
`ProcessPoolExecutor` were both benchmarked against realistic batches of
office documents and PDFs, and both came out *slower* than sequential
conversion — Python's GIL limits real thread parallelism for this CPU-bound
work, and process-spawn overhead outweighs the gains at normal batch sizes.
`run_in_threadpool` is used in `app.py`, but only to keep the server free to
handle *other* concurrent requests while one conversion runs — it's not
claiming to speed up a single batch.

## Project structure

```
tokencraft/
├── app.py                # FastAPI app — routes, local/hosted mode switch
├── core/
│   ├── converter.py        # Thin wrapper over markitdown (bytes in, Markdown out)
│   ├── token_utils.py       # Token & image-token estimation, PDF density heuristic
│   └── folder_utils.py      # Local-only folder picker / open-in-explorer
├── templates/
│   └── index.html          # Dashboard shell (Jinja2)
├── static/
│   ├── style.css
│   └── app.js              # Fetch calls, chart, zip export — no fabricated numbers
├── requirements.txt
├── run.bat / run.sh          # One-click local launchers
├── app.yaml                 # Wasmer Edge config
└── LICENSE
```

## How the token estimates work

- **Text tokens** — `tiktoken`'s `cl100k_base` vocabulary as a close proxy
  (Anthropic hasn't published Claude's exact tokenizer), falling back to a
  ~4-characters-per-token heuristic if the vocab file can't be downloaded.
- **Native PDF/image tokens** — Anthropic's documented formula,
  `tokens ≈ (width_px × height_px) / 750`, long edge scaled to 1568px first,
  with a per-tile cap. For PDFs this is summed across all pages and added to
  the extracted-text token estimate, since PDF vision support processes both
  the page image and the underlying text.
- These are **planning estimates**, not exact billing figures.

## Fast mode (PDFs only)

A toggle in the dashboard that swaps `markitdown`'s PDF converter (which
uses `pdfplumber` for table-aware extraction) for raw `PyMuPDF` text
extraction.

**Measured on a real 20-page report:** 3,838ms → 178ms — about **20x
faster**.

**The trade-off:** you lose table structure. A table like

```
| AI Visibility | Mentions | Citations |
| 67 /100       | 67.32K   | 11.38K    |
```

becomes flat text in reading order instead:

```
AI Visibility
67 /100
Mentions
67.32K
```

Numbers and their labels are no longer explicitly linked — an LLM reading
the fast-mode output has to infer the association from order alone.

**Turn it on for:** text-heavy PDFs with few or no data tables (contracts,
articles, letters, plain reports), or large batches where throughput
matters more than table fidelity.

**Leave it off for:** dashboard/analytics-style PDFs full of tables (SEO
tool exports, financial reports, anything where a number's meaning depends
on which row/column it's in).

Only `.pdf` files are affected. Word, Excel, PowerPoint, images, and audio
conversion are identical either way.

## A note on audio and video

`.mp3`/`.wav` files (and the audio track of `.mp4`) are transcribed via a
**live network call to Google's speech recognition API** — not a local
model, and not something the "Fast mode" toggle above touches at all.
"Video" support is really just audio-track transcription; there's no frame
analysis, OCR-on-video, or visual scene description.

Because it's network-dependent, transcription can be slow or fail outright
on a restricted or slow connection — this is a real risk in **bulk
batches**: without a limit, one stuck network call would hang the entire
request behind it. TokenCraft caps each file at 90 seconds
(`PER_FILE_TIMEOUT_SECONDS` in `app.py`) — a file that exceeds this is
marked as timed-out and skipped so the rest of the batch keeps going.
One caveat worth knowing: Python threads can't be forcibly killed, so an
abandoned slow conversion may keep running quietly in the background even
after its result is discarded — it just won't block your request anymore.

## License

MIT — see [LICENSE](LICENSE).
