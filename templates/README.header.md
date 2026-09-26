<!-- THIS FILE IS GENERATED from papers.yaml by scripts/build_readme.py — edit papers.yaml, not README.md -->
# Awesome TSFM Auditing [![Awesome](https://awesome.re/badge.svg)](https://awesome.re) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md) [![arXiv watch](https://github.com/{{REPO}}/actions/workflows/arxiv-watch.yml/badge.svg)](https://github.com/{{REPO}}/actions/workflows/arxiv-watch.yml) ![papers](https://img.shields.io/badge/papers-{{N_PAPERS}}-blue) ![updated](https://img.shields.io/badge/updated-{{DATE}}-lightgrey)

A curated list of papers on **auditing the pretraining data of time series foundation models (TSFMs)**: pretraining-data / contamination auditing, membership inference, information leakage in TSFM evaluation, and the LLM-side methods that transfer to time series with the fewest modifications.

**Scope.** Time series foundation models are pretrained on large, heterogeneous corpora assembled from public archives; the same archives are then used for zero-shot evaluation, so the reported performance may partly reflect memorisation rather than generalisation. *TSFM auditing* asks whether a given dataset (or window) was seen by a target TSFM during pretraining, and to what extent. The problem is well studied for language models, but most LLM methods rely on next-token probabilities, whereas many TSFMs return numerical forecasts without an explicit likelihood, and time series can re-enter a corpus after rescaling, renaming or resampling. This list therefore (i) collects the still-small set of TSFM-specific work, and (ii) curates the LLM and general-ML literature by **how directly each method maps onto TSFMs** — every method entry carries a one-line *transfer* note.

**Two granularities.** *Window / sample level*: given a forecasting window (context + target), decide member vs. non-member. *Dataset level*: given a dataset, estimate the contamination extent, i.e. the fraction of its samples derived from pretraining sources. Dataset-level decisions can be obtained by aggregating window-level scores with a statistical test (see [Dataset-Level Inference](#dataset-level-inference-and-statistical-contamination-tests)).

**Two strategy families.** *Inference-based* methods score the frozen model (forecast loss, likelihood, embeddings, gradients). *Fine-tuning-based* methods perturb the model — fine-tune it briefly on unseen data or on the audited set — and exploit the asymmetry that non-members change more than members. The second family needs no token probabilities and is where LLM work transfers most directly.

**Ground truth.** Members can be taken from the pretraining sources that a model documents (see [Target Models](#target-models-and-their-documented-pretraining-corpora)). Reliable non-members are observations *generated* after the model's release — not merely datasets *published* after it — which avoids both direct sample overlap and indirect temporal leakage. The resulting temporal shift between members and non-members is itself a confounder; see [Pitfalls](#pitfalls-critiques-and-evaluations-of-auditing-methods) before interpreting any AUC.

<details>
<summary><b>How LLM auditing signals map onto TSFMs (quick reference)</b></summary>

| LLM signal | Requirement | Time-series analogue |
|---|---|---|
| Perplexity / loss | any model | Zero-shot forecast error (MSE, MASE, quantile loss) on the target window |
| Min-K% token probabilities | per-token likelihood | Per-step NLL under a probabilistic head (Moirai, Sundial, TiRex) or token probabilities (Chronos); frequency-domain variant on residuals (TSFMAudit) |
| Reference-model ratio (LiRA) | reference models | Loss ratio against scratch-trained or non-TS-pretrained references (e.g., VisionTS, TabPFN-TS) |
| Neighbourhood comparison | perturbations | Loss relative to augmented copies (jitter, scaling, warping, resampling) |
| Fine-tuned score deviation | fine-tuning access | LoRA-fine-tune on post-release data; compare loss before/after |
| Embedding geometry shift (KDS) | embeddings | Kernel divergence of hidden-state similarities before/after one epoch on the audited set |
| Gradient deviation | gradients | Gradient norm / concentration on the forecasting head or adapters |
| Dataset inference | many samples | Aggregate window scores over a dataset; test against a post-release validation split |

</details>

**Legend.** *Level*: `sample` / `dataset` / `both`. *Access*: `black-box` = predictions only · `grey-box` = likelihoods or embeddings · `white-box` = gradients or fine-tuning. *Domain*: `ts` time series · `llm` language models · `ml` general ML.

## Contents

{{TOC}}

{{SECTIONS}}

## Maintenance and Auto-Update

`README.md` is generated from [`papers.yaml`](papers.yaml) by [`scripts/build_readme.py`](scripts/build_readme.py). A [GitHub Actions workflow](.github/workflows/arxiv-watch.yml) queries the arXiv API every week for new submissions matching time-series × auditing keyword combinations (and foundation-model auditing methods that may transfer), removes anything already listed or already proposed, and opens a pull request with the candidates in [`candidates/`](candidates/). When the arXiv search API is unavailable (it intermittently rejects automated clients), the watch falls back to harvesting arXiv's OAI-PMH feed for the `cs`/`stat` sets and then to OpenAlex; the source used and per-query counts are recorded in [`data/last_run.json`](data/last_run.json). Nothing enters the list without review. To accept a candidate, run

```bash
python scripts/add_paper.py <arXiv-id> --category <category-key>   # fetches metadata, appends a stub to papers.yaml
python scripts/build_readme.py                                      # regenerates README.md
```

then fill in the `transfer` / `note` line. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and the category keys.

## Related Lists

- [lyy1994/awesome-data-contamination](https://github.com/lyy1994/awesome-data-contamination) — data contamination for LLM evaluation
- [yale-nlp/lm-contamination-survey](https://github.com/yale-nlp/lm-contamination-survey) — paper list accompanying the ACL 2024 survey
- [velvinnn/LLM_MIA](https://github.com/velvinnn/LLM_MIA) — case studies for *Does Data Contamination Detection Work (Well) for LLMs?*
- [iamgroot42/mimir](https://github.com/iamgroot42/mimir) — MIMIR: reference implementations of LLM membership inference attacks
- [CryptoAILab/Awesome-LM-SSP](https://github.com/CryptoAILab/Awesome-LM-SSP) — safety, security and privacy of large models (has a membership-inference section)

## Contributing

Contributions are welcome — open a pull request that edits `papers.yaml` (not `README.md`), or open an issue using the *Add a paper* template. Inclusion criteria: the paper audits, attacks, or evaluates the pretraining/training data of a time-series model, **or** it is an LLM / general-ML auditing method whose signal is available from a TSFM (loss, likelihood, embeddings, gradients, fine-tuning) with little modification. Please state the transfer argument in the `transfer` field.

## License

[CC0 1.0](LICENSE) — to the extent possible under law, the maintainers have waived all copyright and related rights to this list.
