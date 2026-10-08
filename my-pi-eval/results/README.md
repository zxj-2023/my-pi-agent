# Terminal-Bench 2.0 评测结果对比中心 (Evaluation Results Center)

本目录用于统一归档、追踪和对比 **原厂 Pi Agent** 与 **自研 My-Pi-Agent** 在 Terminal-Bench 2.0 基准测试下的实际表现。

---

## 📊 核心对比总榜 (Leaderboard Comparison)

- **基准测试集**：Terminal-Bench 2.0 (全量 89 题)
- **底层模型**：DeepSeek-V4.1-Flash (`deepseek/deepseek-chat`)
- **评测环境**：Docker Sandbox (Windows WSL2 / Linux Container)
- **原厂 Pi 进度**：已完成 **89 / 89** 题，通过 **9** 题，当前通过率 **10.1%**

| 任务 ID (Task ID) | 原厂 Pi Agent (Official) | 自研 My-Pi-Agent | 相对效率 (Tokens / Time) | 详细报告 |
|---|:---:|:---:|:---:|:---:|
| `adaptive-rejection-sampler` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 147s | [查看战报](./pi_official_terminal_bench_2.md#adaptive-rejection-sampler) |
| `bn-fit-modify` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 442s / 100326 tok | [查看战报](./pi_official_terminal_bench_2.md#bn-fit-modify) |
| `break-filter-js-from-html` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 12s | [查看战报](./pi_official_terminal_bench_2.md#break-filter-js-from-html) |
| `build-cython-ext` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 180s / 1269476 tok | [查看战报](./pi_official_terminal_bench_2.md#build-cython-ext) |
| `build-pmars` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 12s | [查看战报](./pi_official_terminal_bench_2.md#build-pmars) |
| `build-pov-ray` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 12s | [查看战报](./pi_official_terminal_bench_2.md#build-pov-ray) |
| `caffe-cifar-10` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 384s | [查看战报](./pi_official_terminal_bench_2.md#caffe-cifar-10) |
| `cancel-async-tasks` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#cancel-async-tasks) |
| `chess-best-move` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#chess-best-move) |
| `circuit-fibsqrt` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 62s | [查看战报](./pi_official_terminal_bench_2.md#circuit-fibsqrt) |
| `cobol-modernization` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#cobol-modernization) |
| `code-from-image` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 85s | [查看战报](./pi_official_terminal_bench_2.md#code-from-image) |
| `compile-compcert` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 110s | [查看战报](./pi_official_terminal_bench_2.md#compile-compcert) |
| `configure-git-webserver` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 144606 tok | [查看战报](./pi_official_terminal_bench_2.md#configure-git-webserver) |
| `constraints-scheduling` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 141s | [查看战报](./pi_official_terminal_bench_2.md#constraints-scheduling) |
| `count-dataset-tokens` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 742754 tok | [查看战报](./pi_official_terminal_bench_2.md#count-dataset-tokens) |
| `crack-7z-hash` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 90s | [查看战报](./pi_official_terminal_bench_2.md#crack-7z-hash) |
| `custom-memory-heap-crash` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 383s | [查看战报](./pi_official_terminal_bench_2.md#custom-memory-heap-crash) |
| `db-wal-recovery` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 106s | [查看战报](./pi_official_terminal_bench_2.md#db-wal-recovery) |
| `distribution-search` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 98s | [查看战报](./pi_official_terminal_bench_2.md#distribution-search) |
| `dna-assembly` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 251s | [查看战报](./pi_official_terminal_bench_2.md#dna-assembly) |
| `dna-insert` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 141s | [查看战报](./pi_official_terminal_bench_2.md#dna-insert) |
| `extract-elf` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 58s | [查看战报](./pi_official_terminal_bench_2.md#extract-elf) |
| `extract-moves-from-video` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 124s | [查看战报](./pi_official_terminal_bench_2.md#extract-moves-from-video) |
| `feal-differential-cryptanalysis` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 90s | [查看战报](./pi_official_terminal_bench_2.md#feal-differential-cryptanalysis) |
| `feal-linear-cryptanalysis` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 62s | [查看战报](./pi_official_terminal_bench_2.md#feal-linear-cryptanalysis) |
| `filter-js-from-html` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 113s | [查看战报](./pi_official_terminal_bench_2.md#filter-js-from-html) |
| `financial-document-processor` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 69s | [查看战报](./pi_official_terminal_bench_2.md#financial-document-processor) |
| `fix-code-vulnerability` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 58s | [查看战报](./pi_official_terminal_bench_2.md#fix-code-vulnerability) |
| `fix-git` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 46s | [查看战报](./pi_official_terminal_bench_2.md#fix-git) |
| `fix-ocaml-gc` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 1314306 tok | [查看战报](./pi_official_terminal_bench_2.md#fix-ocaml-gc) |
| `gcode-to-text` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 379s | [查看战报](./pi_official_terminal_bench_2.md#gcode-to-text) |
| `git-leak-recovery` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 62s | [查看战报](./pi_official_terminal_bench_2.md#git-leak-recovery) |
| `git-multibranch` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 465s / 398285 tok | [查看战报](./pi_official_terminal_bench_2.md#git-multibranch) |
| `gpt2-codegolf` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 27s | [查看战报](./pi_official_terminal_bench_2.md#gpt2-codegolf) |
| `headless-terminal` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 176s | [查看战报](./pi_official_terminal_bench_2.md#headless-terminal) |
| `hf-model-inference` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 70s | [查看战报](./pi_official_terminal_bench_2.md#hf-model-inference) |
| `install-windows-3.11` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 1368516 tok | [查看战报](./pi_official_terminal_bench_2.md#install-windows-3.11) |
| `kv-store-grpc` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 151s | [查看战报](./pi_official_terminal_bench_2.md#kv-store-grpc) |
| `large-scale-text-editing` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 42s | [查看战报](./pi_official_terminal_bench_2.md#large-scale-text-editing) |
| `largest-eigenval` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 381s | [查看战报](./pi_official_terminal_bench_2.md#largest-eigenval) |
| `llm-inference-batching-scheduler` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 77s | [查看战报](./pi_official_terminal_bench_2.md#llm-inference-batching-scheduler) |
| `log-summary-date-ranges` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 88s | [查看战报](./pi_official_terminal_bench_2.md#log-summary-date-ranges) |
| `mailman` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 2276447 tok | [查看战报](./pi_official_terminal_bench_2.md#mailman) |
| `make-doom-for-mips` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 6669373 tok | [查看战报](./pi_official_terminal_bench_2.md#make-doom-for-mips) |
| `make-mips-interpreter` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 8706443 tok | [查看战报](./pi_official_terminal_bench_2.md#make-mips-interpreter) |
| `mcmc-sampling-stan` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 176560 tok | [查看战报](./pi_official_terminal_bench_2.md#mcmc-sampling-stan) |
| `merge-diff-arc-agi-task` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 115s | [查看战报](./pi_official_terminal_bench_2.md#merge-diff-arc-agi-task) |
| `model-extraction-relu-logits` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 82s | [查看战报](./pi_official_terminal_bench_2.md#model-extraction-relu-logits) |
| `modernize-scientific-stack` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 46s | [查看战报](./pi_official_terminal_bench_2.md#modernize-scientific-stack) |
| `mteb-leaderboard` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 72s | [查看战报](./pi_official_terminal_bench_2.md#mteb-leaderboard) |
| `mteb-retrieve` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 51s | [查看战报](./pi_official_terminal_bench_2.md#mteb-retrieve) |
| `multi-source-data-merger` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 43s | [查看战报](./pi_official_terminal_bench_2.md#multi-source-data-merger) |
| `nginx-request-logging` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 1s | [查看战报](./pi_official_terminal_bench_2.md#nginx-request-logging) |
| `openssl-selfsigned-cert` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 37s | [查看战报](./pi_official_terminal_bench_2.md#openssl-selfsigned-cert) |
| `overfull-hbox` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 185s | [查看战报](./pi_official_terminal_bench_2.md#overfull-hbox) |
| `password-recovery` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 50s | [查看战报](./pi_official_terminal_bench_2.md#password-recovery) |
| `path-tracing` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 37s | [查看战报](./pi_official_terminal_bench_2.md#path-tracing) |
| `path-tracing-reverse` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 4492022 tok | [查看战报](./pi_official_terminal_bench_2.md#path-tracing-reverse) |
| `polyglot-c-py` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 159s | [查看战报](./pi_official_terminal_bench_2.md#polyglot-c-py) |
| `polyglot-rust-c` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 138s | [查看战报](./pi_official_terminal_bench_2.md#polyglot-rust-c) |
| `portfolio-optimization` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 55s | [查看战报](./pi_official_terminal_bench_2.md#portfolio-optimization) |
| `protein-assembly` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 729s / 719052 tok | [查看战报](./pi_official_terminal_bench_2.md#protein-assembly) |
| `prove-plus-comm` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 465s / 34060 tok | [查看战报](./pi_official_terminal_bench_2.md#prove-plus-comm) |
| `pypi-server` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 34s | [查看战报](./pi_official_terminal_bench_2.md#pypi-server) |
| `pytorch-model-cli` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 286203 tok | [查看战报](./pi_official_terminal_bench_2.md#pytorch-model-cli) |
| `pytorch-model-recovery` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 58s | [查看战报](./pi_official_terminal_bench_2.md#pytorch-model-recovery) |
| `qemu-alpine-ssh` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 40s | [查看战报](./pi_official_terminal_bench_2.md#qemu-alpine-ssh) |
| `qemu-startup` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 53s | [查看战报](./pi_official_terminal_bench_2.md#qemu-startup) |
| `query-optimize` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 811s / 65722 tok | [查看战报](./pi_official_terminal_bench_2.md#query-optimize) |
| `raman-fitting` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 20s | [查看战报](./pi_official_terminal_bench_2.md#raman-fitting) |
| `regex-chess` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 21s | [查看战报](./pi_official_terminal_bench_2.md#regex-chess) |
| `regex-log` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 21s | [查看战报](./pi_official_terminal_bench_2.md#regex-log) |
| `reshard-c4-data` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 22s | [查看战报](./pi_official_terminal_bench_2.md#reshard-c4-data) |
| `rstan-to-pystan` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 21s | [查看战报](./pi_official_terminal_bench_2.md#rstan-to-pystan) |
| `sam-cell-seg` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 22s | [查看战报](./pi_official_terminal_bench_2.md#sam-cell-seg) |
| `sanitize-git-repo` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 21s | [查看战报](./pi_official_terminal_bench_2.md#sanitize-git-repo) |
| `schemelike-metacircular-eval` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 855s / 1446358 tok | [查看战报](./pi_official_terminal_bench_2.md#schemelike-metacircular-eval) |
| `sparql-university` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 447s / 158711 tok | [查看战报](./pi_official_terminal_bench_2.md#sparql-university) |
| `sqlite-db-truncate` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 89s | [查看战报](./pi_official_terminal_bench_2.md#sqlite-db-truncate) |
| `sqlite-with-gcov` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 725s / 143223 tok | [查看战报](./pi_official_terminal_bench_2.md#sqlite-with-gcov) |
| `torch-pipeline-parallelism` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 874s / 385517 tok | [查看战报](./pi_official_terminal_bench_2.md#torch-pipeline-parallelism) |
| `torch-tensor-parallelism` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 178s | [查看战报](./pi_official_terminal_bench_2.md#torch-tensor-parallelism) |
| `train-fasttext` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 381s | [查看战报](./pi_official_terminal_bench_2.md#train-fasttext) |
| `tune-mjcf` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 900s / 79014 tok | [查看战报](./pi_official_terminal_bench_2.md#tune-mjcf) |
| `video-processing` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 153s | [查看战报](./pi_official_terminal_bench_2.md#video-processing) |
| `vulnerable-secret` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 333s / 52711 tok | [查看战报](./pi_official_terminal_bench_2.md#vulnerable-secret) |
| `winning-avg-corewars` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 639s / 726837 tok | [查看战报](./pi_official_terminal_bench_2.md#winning-avg-corewars) |
| `write-compressor` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 586s / 885437 tok | [查看战报](./pi_official_terminal_bench_2.md#write-compressor) |

---

## 📁 目录结构说明

- [`pi_official_terminal_bench_2.md`](./pi_official_terminal_bench_2.md)：**原厂 Pi 官方 Agent** 的评测记录与单题详报（基线 Baseline）。
- [`my_pi_agent_terminal_bench_2.md`](./my_pi_agent_terminal_bench_2.md)：**自研 My-Pi-Agent** 的评测记录与单题详报。
- [`comparison_matrix.md`](./comparison_matrix.md)：两者的**深度横向对比分析**（架构差异、Token 开销、工具调用效率、错误自愈能力）。
