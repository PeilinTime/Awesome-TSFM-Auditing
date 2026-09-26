# Contributing

Thank you for helping keep this list useful. The list is maintained through a single data file, **`papers.yaml`**; `README.md` is generated from it and should not be edited by hand.

## Inclusion criteria

A paper belongs here if at least one of the following holds:

1. It audits, attacks, or evaluates the **pretraining / training data of a time-series model** (membership inference, contamination auditing, information leakage, memorisation, provenance).
2. It is an **LLM or general-ML auditing method whose signal a TSFM can provide** (a loss, a likelihood, an embedding, a gradient, or a fine-tuning response), so that it transfers to time series with little modification. In this case the `transfer` field must say *how*.
3. It documents the **pretraining corpus of a mainstream TSFM** or provides a **leakage-aware benchmark / evaluation protocol**.

Out of scope: general TSFM architecture papers, general time-series privacy (e.g., differential privacy without membership inference), benchmark contamination detection for LLM evaluation (prompt-based methods such as guided completion, quizzes, or rephrasing tests), and look-ahead bias in LLM-based forecasting unless the paper provides a detection method that applies to numerical forecasting models. The list stays focused on methods that can be applied to TSFMs.

## Adding a paper

```bash
pip install -r requirements.txt
python scripts/add_paper.py <arXiv-id> --category <category-key>   # fetches metadata, appends a stub
# edit the stub in papers.yaml: level / access / signal / transfer (or note) / code
python scripts/build_readme.py                                      # validates and regenerates README.md
```

`add_paper.py` also stores the abstract in `data/abstracts.json`, which README.md folds under the title; for a paper without an arXiv version add the abstract there by hand, keyed by the entry id. The *Fetch abstracts* workflow (Actions tab) fills in any that are missing.

Open a pull request with the change to `papers.yaml` (and the regenerated `README.md` if you ran the script; CI regenerates it on merge either way). If you prefer not to clone, open an issue with the *Add a paper* template.

### Category keys

| key | section |
|---|---|
| `tsfm-auditing` | Auditing Methods for Time Series Foundation Models |
| `tsfm-leakage-eval` | Information Leakage and Leakage-Aware Evaluation of TSFMs |
| `ts-mia` | Membership Inference and Privacy for Time-Series Models |
| `llm-finetune` | Fine-Tuning and Adaptation-Dynamics-Based Detection |
| `llm-loss-reference` | Loss-, Reference- and Gradient-Based Membership Inference |
| `llm-score` | Token-Probability Scoring Functions |
| `llm-dataset-level` | Dataset-Level Inference and Statistical Contamination Tests |
| `pitfalls` | Pitfalls, Critiques and Evaluations of Auditing Methods |
| `surveys` | Surveys |
| `provenance` | Proactive Provenance: Data Watermarks and Copyright Traps |
| `tsfm-models` | Target Models and Their Documented Pretraining Corpora |
| `ts-benchmarks` | Benchmarks and Evaluation Suites |

### Entry fields

```yaml
- id: fsd                       # unique slug
  title: "Fine-tuning can Help Detect Pretraining Data from Large Language Models"
  authors: "Hengxiang Zhang, Songxin Zhang, Bingyi Jing, et al."   # first three, then et al.
  year: 2024                    # year of first arXiv submission
  venue: "ICLR 2025"            # or "arXiv 2024"
  arxiv: "2410.10880"           # without version; use url: instead if there is no arXiv version
  code: "https://github.com/ml-stat-Sustech/Fine-tuned-Score-Deviation"
  category: llm-finetune
  domain: llm                   # ts | llm | ml
  level: sample                 # sample | dataset | both
  access: white-box             # black-box (predictions) | grey-box (likelihoods/embeddings) | white-box (gradients/fine-tuning)
  signal: "..."                 # what is measured
  transfer: "..."               # how it maps onto TSFM auditing (method sections)
  # note: "..."                 # one-liner for models / benchmarks / surveys / pitfalls
  # model / corpus / corpus_url # models only
```

Keep `signal` and `transfer` to one sentence each, in neutral, technical language. Do not add evaluative adjectives.

## The weekly arXiv watch

`.github/workflows/arxiv-watch.yml` runs `scripts/arxiv_watch.py` every Monday (and on demand from the *Actions* tab → *arXiv watch* → *Run workflow*, optionally with a custom look-back window). The script queries the arXiv API, drops papers already listed or already proposed (`data/seen.json`), scores the rest by keyword hits, and opens a pull request whose body lists the candidates (Tier A: time-series specific; Tier B: foundation-model auditing methods to check for transferability). Merging that PR only archives the report under `candidates/`; adding a paper is a separate, manual step as described above. If a candidate was rejected by mistake, delete its id from `data/seen.json` and it will be proposed again.

Sources are tried in order: the arXiv search API (`QUERIES`), then arXiv's OAI-PMH feed (complete harvest of the `cs` and `stat` sets since the window start, filtered locally by the same keyword scoring), then OpenAlex (`OPENALEX_QUERIES`; set a repository variable `OPENALEX_MAILTO` with a contact e-mail to use OpenAlex's polite pool). `data/last_run.json` records which source answered and how many results each query returned; a run that gets nothing from any source fails visibly and does not advance the window.

To tune what the watch looks for, edit `QUERIES`, `OPENALEX_QUERIES`, `TS_TERMS`, `FM_TERMS` and `AUDIT_TERMS` at the top of `scripts/arxiv_watch.py`, then test with

```bash
python scripts/arxiv_watch.py --days 30 --dry-run
```
