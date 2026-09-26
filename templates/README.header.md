<!-- THIS FILE IS GENERATED from papers.yaml by scripts/build_readme.py; edit papers.yaml, not README.md -->
# Awesome TSFM Auditing [![Awesome](https://awesome.re/badge.svg)](https://awesome.re) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md) [![arXiv watch](https://github.com/{{REPO}}/actions/workflows/arxiv-watch.yml/badge.svg)](https://github.com/{{REPO}}/actions/workflows/arxiv-watch.yml) ![papers](https://img.shields.io/badge/papers-{{N_PAPERS}}-blue) ![updated](https://img.shields.io/badge/updated-{{DATE}}-lightgrey)

A curated list of papers on **auditing the pretraining data of time series foundation models (TSFMs)**: pretraining-data / contamination auditing, membership inference, information leakage in TSFM evaluation, and relevant methods from the LLM/NLP domain that may be transferable to time series with minor modifications.

**Scope.** Time series foundation models (TSFMs) are pretrained on large, heterogeneous time series corpora. Some evaluation datasets may (partly) overlap with pretraining data, potentially inflating the reported performance and obscuring the models' generalization ability to unseen data. *TSFM auditing* aims to determine whether a given time-series sample or dataset has been seen during the target TSFM's pretraining, and to what extent. While pretraining-data auditing has been extensively studied for large language models (LLMs), many existing methods rely on token probabilities/distributions that are not readily available from TSFMs, which typically output numerical predictions without likelihoods. Moreover, the same underlying time series may reappear under different names, scales, or sampling frequencies, making contamination detection more challenging. This list collects research on pretraining-data auditing for TSFMs, along with relevant methods from the LLM/NLP and broader machine learning literature that are potentially adaptable to time series.

**Legend.** *Level*: `sample` / `dataset` / `both`. *Access*: `black-box` = predictions only · `grey-box` = likelihoods or embeddings · `white-box` = gradients or fine-tuning. *Domain*: `ts` time series · `llm` language models · `ml` general ML.

## 📖 Contents

{{TOC}}

{{SECTIONS}}


## 🔗 Related Lists

Benchmark contamination detection for LLM evaluation is outside the scope of this list; for that topic see:

- [lyy1994/awesome-data-contamination](https://github.com/lyy1994/awesome-data-contamination): data contamination in LLM evaluation
- [yale-nlp/lm-contamination-survey](https://github.com/yale-nlp/lm-contamination-survey): paper list accompanying the ACL 2024 survey

Membership inference on language models:

- [iamgroot42/mimir](https://github.com/iamgroot42/mimir): MIMIR, reference implementations of LLM membership inference attacks
- [velvinnn/LLM_MIA](https://github.com/velvinnn/LLM_MIA): case studies for *Does Data Contamination Detection Work (Well) for LLMs?*
- [CryptoAILab/Awesome-LM-SSP](https://github.com/CryptoAILab/Awesome-LM-SSP): safety, security and privacy of large models (has a membership-inference section)

## ✍️ Contributing

Contributions are welcome: open a pull request that edits `papers.yaml` (not `README.md`), or open an issue using the *Add a paper* template. Inclusion criteria: the paper audits, attacks, or evaluates the pretraining/training data of a time-series model, **or** it is an LLM / general-ML auditing method whose signal is available from a TSFM (loss, likelihood, embeddings, gradients, fine-tuning) with little modification. Please state the transfer argument in the `transfer` field.

## ⚖️ License

[CC0 1.0](LICENSE). To the extent possible under law, the maintainers have waived all copyright and related rights to this list.
