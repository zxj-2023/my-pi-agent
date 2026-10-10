# Terminal-Bench 2.1 终局横向对比矩阵 (MyPiAgent vs 官方 Pi)

> **底座大模型**：DeepSeek-V4.1 (`deepseek/deepseek-chat`)  
> **运行环境**：完全一致的本地物理机、相同 Docker 镜像与评测脚本  
> **总有效题目**：85 道 (排除 4 道单机物理极限题) / 89 道 (全量题集)  
> **生成时间**：2026-10-10 15:40:56  

---

## 一、 顶峰对决量化概览

| 指标 | 自研 MyPiAgent | 官方 Pi Coding Agent | 胜出方与差距 |
| :--- | :---: | :---: | :--- |
| **89 题全量通过题数** | **71 道 (79.78%)** | **74 道 (83.15%)** | 工业基准高度逼近 |
| **85 题常规有效通过题数** | **71 道 (83.53%)** | **74 道 (87.06%)** | 均展现顶级自动化能力 |
| **双胜题目数 (两边均通过)** | **67 道** | 67 道 | 67 道高难度赛题两边均满分攻克 |
| **MyPiAgent 独占胜出题目** | **4 道** 🌟 | - | 自研 Agent 满分（官方 Pi 彻底折戟） |
| **官方 Pi 独占胜出题目** | - | **7 道** | 官方 Pi 满分（自研 Agent 格式微差） |
| **双负题目数 (两边均未过)** | **11 道** | 11 道 | 包含 4 道单机物理极限及上游环境断言题 |

---

## 二、 自研 MyPiAgent 独占胜出赛题 (4 道 🌟)

在完全相同的物理环境与模型下，自研 Agent 在以下高难度赛题上斩获满分，而官方 Pi 彻底失败：

- **`cancel-async-tasks`**：原厂 Pi 失败，自研 Agent 斩获 1.0 满分！
- **`make-mips-interpreter`**：原厂 Pi 失败，自研 Agent 斩获 1.0 满分！
- **`polyglot-c-py`**：原厂 Pi 失败，自研 Agent 斩获 1.0 满分！
- **`pytorch-model-cli`**：原厂 Pi 失败，自研 Agent 斩获 1.0 满分！

---

## 三、 官方 Pi 独占胜出赛题 (7 道)

- `gcode-to-text`：官方 Pi 满分，自研 Agent 未过。
- `large-scale-text-editing`：官方 Pi 满分，自研 Agent 未过。
- `polyglot-rust-c`：官方 Pi 满分，自研 Agent 未过。
- `raman-fitting`：官方 Pi 满分，自研 Agent 未过。
- `torch-pipeline-parallelism`：官方 Pi 满分，自研 Agent 未过。
- `train-fasttext`：官方 Pi 满分，自研 Agent 未过。
- `video-processing`：官方 Pi 满分，自研 Agent 未过。

---

## 四、 89 题全量对照表

| 序号 | 任务名称 | 自研 MyPiAgent | 官方 Pi | 对比结果 |
| :---: | :--- | :---: | :---: | :---: |
| 01 | `adaptive-rejection-sampler` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 02 | `bn-fit-modify` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 03 | `break-filter-js-from-html` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 04 | `build-cython-ext` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 05 | `build-pmars` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 06 | `build-pov-ray` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 07 | `caffe-cifar-10` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 08 | `cancel-async-tasks` | ✅ PASSED | ❌ FAILED | 🏆 **MyPi 独占胜出** |
| 09 | `chess-best-move` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 10 | `circuit-fibsqrt` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 11 | `cobol-modernization` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 12 | `code-from-image` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 13 | `compile-compcert` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 14 | `configure-git-webserver` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 15 | `constraints-scheduling` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 16 | `count-dataset-tokens` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 17 | `crack-7z-hash` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 18 | `custom-memory-heap-crash` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 19 | `db-wal-recovery` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 20 | `distribution-search` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 21 | `dna-assembly` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 22 | `dna-insert` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 23 | `extract-elf` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 24 | `extract-moves-from-video` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 25 | `feal-differential-cryptanalysis` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 26 | `feal-linear-cryptanalysis` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 27 | `filter-js-from-html` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 28 | `financial-document-processor` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 29 | `fix-code-vulnerability` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 30 | `fix-git` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 31 | `fix-ocaml-gc` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 32 | `gcode-to-text` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 33 | `git-leak-recovery` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 34 | `git-multibranch` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 35 | `gpt2-codegolf` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 36 | `headless-terminal` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 37 | `hf-model-inference` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 38 | `install-windows-3.11` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 39 | `kv-store-grpc` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 40 | `large-scale-text-editing` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 41 | `largest-eigenval` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 42 | `llm-inference-batching-scheduler` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 43 | `log-summary-date-ranges` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 44 | `mailman` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 45 | `make-doom-for-mips` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 46 | `make-mips-interpreter` | ✅ PASSED | ❌ FAILED | 🏆 **MyPi 独占胜出** |
| 47 | `mcmc-sampling-stan` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 48 | `merge-diff-arc-agi-task` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 49 | `model-extraction-relu-logits` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 50 | `modernize-scientific-stack` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 51 | `mteb-leaderboard` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 52 | `mteb-retrieve` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 53 | `multi-source-data-merger` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 54 | `nginx-request-logging` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 55 | `openssl-selfsigned-cert` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 56 | `overfull-hbox` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 57 | `password-recovery` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 58 | `path-tracing` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 59 | `path-tracing-reverse` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 60 | `polyglot-c-py` | ✅ PASSED | ❌ FAILED | 🏆 **MyPi 独占胜出** |
| 61 | `polyglot-rust-c` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 62 | `portfolio-optimization` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 63 | `protein-assembly` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 64 | `prove-plus-comm` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 65 | `pypi-server` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 66 | `pytorch-model-cli` | ✅ PASSED | ❌ FAILED | 🏆 **MyPi 独占胜出** |
| 67 | `pytorch-model-recovery` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 68 | `qemu-alpine-ssh` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 69 | `qemu-startup` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 70 | `query-optimize` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 71 | `raman-fitting` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 72 | `regex-chess` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 73 | `regex-log` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 74 | `reshard-c4-data` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 75 | `rstan-to-pystan` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 76 | `sam-cell-seg` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 77 | `sanitize-git-repo` | ❌ FAILED | ❌ FAILED | 🧱 双双折戟 |
| 78 | `schemelike-metacircular-eval` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 79 | `sparql-university` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 80 | `sqlite-db-truncate` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 81 | `sqlite-with-gcov` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 82 | `torch-pipeline-parallelism` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 83 | `torch-tensor-parallelism` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 84 | `train-fasttext` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 85 | `tune-mjcf` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 86 | `video-processing` | ❌ FAILED | ✅ PASSED | 📌 官方 Pi 胜出 |
| 87 | `vulnerable-secret` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 88 | `winning-avg-corewars` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
| 89 | `write-compressor` | ✅ PASSED | ✅ PASSED | 🤝 双双满分 |
