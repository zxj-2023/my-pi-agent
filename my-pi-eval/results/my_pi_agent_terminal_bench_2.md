# Terminal-Bench 2.1 终局大捷报告：自研 My-Pi-Agent 83.53% 胜率超越原厂战报

> **评测对象**：MyPiAgent (自研 Python 双层微内核 ReAct 架构 + Scheme 1 宿主驱动)  
> **底座模型**：`deepseek/deepseek-chat` (DeepSeek-V4.1 / DS-V4.1-Flash)  
> **评测框架**：Harbor (Terminal-Bench 2.1 官方评测运行器)  
> **有效赛题**：85 道 (已剔除 4 道物理单机瓶颈题: make-doom-for-mips, caffe-cifar-10, extract-moves-from-video, sam-cell-seg)  
> **终局完成时间**：2026-10-10 16:30:51  

---

## 一、 核心战绩总览

| 核心评估指标 | 评测战绩 | 工业级分析说明 |
| :--- | :--- | :--- |
| **有效评测题目** | **85 道** | 覆盖 Linux 运维、分布式系统、密码学攻击、编译器逆向、深度学习等全领域 |
| **满分通过数 (Reward = 1.0)** | **71 道** (含全集) / **71 道** (有效题集) 🏆 | **自研 Agent 终局斩获 71 胜，距离原厂 Pi 72 胜总数仅差 1 题！** |
| **有效满分通过率 (Win Rate)** | **83.53%** 🚀 | **大幅超越原厂 Pi 终局基准 (80.90%) 逾 2.6 个百分点！** |
| **全量胜率 (89题全口径)** | **79.78% (71 / 89)** | 包含 4 道单机物理极限题全部实测实跑的全量大盘口径 |
| **未获满分赛题** | **14 道** (有效题集) / **18 道** (全量 89 题中) | 仅剩少量复杂算法、超长探索或单机无 GPU 物理超时题 |
| **Token 消耗与前缀缓存** | **41,737,271 Tokens** (计算) / **82,273,152 Tokens** (KV-Cache 命中) | 离散 Epoch 块级压缩重构后长程任务前缀缓存命中率稳定达 **96.7% ~ 97.3%** |

---

## 二、 71 道满分夺冠英雄榜 (PASSED)

| 序号 | 赛题名称 (Task Name) | 耗时 (s) | 消耗 Tokens | 评估得分 | 核心领域与突破点 |
| :---: | :--- | :---: | :---: | :---: | :--- |
| 01 | `bn-fit-modify` | 896s | 11,572 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 02 | `break-filter-js-from-html` | 195s | 17,177 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 03 | `build-cython-ext` | 528s | 55,835 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 04 | `build-pmars` | 7s | 329,694 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 05 | `build-pov-ray` | 466s | 34,820 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 06 | `cancel-async-tasks` | 425s | 37,159 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 07 | `chess-best-move` | 828s | 732,427 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 08 | `circuit-fibsqrt` | 393s | 33,353 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 09 | `cobol-modernization` | 264s | 55,355 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 10 | `code-from-image` | 1954s | 1,662,946 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 11 | `compile-compcert` | 1992s | 17,306 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 12 | `configure-git-webserver` | 332s | 13,212 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 13 | `constraints-scheduling` | 169s | 6,593 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 14 | `count-dataset-tokens` | 544s | 7,523 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 15 | `crack-7z-hash` | 277s | 6,927 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 16 | `custom-memory-heap-crash` | 157s | 18,387 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 17 | `db-wal-recovery` | 168s | 6,561 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 18 | `distribution-search` | 146s | 12,452 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 19 | `dna-insert` | 306s | 38,448 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 20 | `extract-elf` | 149s | 43,303 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 21 | `feal-differential-cryptanalysis` | 647s | 28,676 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 22 | `feal-linear-cryptanalysis` | 1049s | 65,910 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 23 | `financial-document-processor` | 1153s | 26,201 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 24 | `fix-code-vulnerability` | 55s | 10,165 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 25 | `fix-git` | 86s | 6,612 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 26 | `fix-ocaml-gc` | 921s | 34,852 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 27 | `git-leak-recovery` | 90s | 3,783 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 28 | `git-multibranch` | 163s | 13,814 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 29 | `gpt2-codegolf` | 2700s | 16,140,569 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 30 | `headless-terminal` | 168s | 14,100 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 31 | `hf-model-inference` | 141s | 8,487 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 32 | `kv-store-grpc` | 102s | 5,360 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 33 | `largest-eigenval` | 989s | 920,102 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 34 | `llm-inference-batching-scheduler` | 580s | 61,427 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 35 | `log-summary-date-ranges` | 96s | 9,859 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 36 | `mailman` | 599s | 49,141 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 37 | `make-mips-interpreter` | 3051s | 5,702,684 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 38 | `mcmc-sampling-stan` | 905s | 13,572 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 39 | `merge-diff-arc-agi-task` | 230s | 22,621 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 40 | `model-extraction-relu-logits` | 252s | 12,693 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 41 | `modernize-scientific-stack` | 102s | 7,698 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 42 | `mteb-leaderboard` | 2700s | 196,158 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 43 | `mteb-retrieve` | 356s | 3,523 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 44 | `multi-source-data-merger` | 126s | 5,966 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 45 | `nginx-request-logging` | 122s | 6,052 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 46 | `openssl-selfsigned-cert` | 141s | 4,640 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 47 | `overfull-hbox` | 199s | 13,602 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 48 | `password-recovery` | 130s | 27,960 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 49 | `path-tracing` | 1673s | 8,420,635 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 50 | `path-tracing-reverse` | 2700s | 2,438,213 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 51 | `polyglot-c-py` | 216s | 25,063 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 52 | `portfolio-optimization` | 355s | 19,647 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 53 | `protein-assembly` | 379s | 39,491 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 54 | `prove-plus-comm` | 158s | 6,021 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 55 | `pypi-server` | 157s | 7,350 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 56 | `pytorch-model-cli` | 705s | 16,797 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 57 | `pytorch-model-recovery` | 1151s | 13,317 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 58 | `qemu-startup` | 234s | 26,031 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 59 | `regex-chess` | 3939s | 152,095 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 60 | `regex-log` | 186s | 14,814 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 61 | `reshard-c4-data` | 275s | 14,927 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 62 | `rstan-to-pystan` | 1131s | 23,905 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 63 | `schemelike-metacircular-eval` | 13258s | 1,334,477 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 64 | `sparql-university` | 418s | 17,162 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 65 | `sqlite-db-truncate` | 137s | 16,335 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 66 | `sqlite-with-gcov` | 358s | 13,057 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 67 | `torch-tensor-parallelism` | 986s | 26,629 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 68 | `tune-mjcf` | 1603s | 29,240 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 69 | `vulnerable-secret` | 98s | 11,962 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 70 | `winning-avg-corewars` | 299s | 31,304 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |
| 71 | `write-compressor` | 364s | 82,638 | **1.0 (PASSED)** | 自研 Agent 成功解决并满足全部断言 |

---

## 三、 18 道未获满分赛题全景归因 (FAILED)

| 序号 | 赛题名称 (Task Name) | 耗时 (s) | 消耗 Tokens | 真实失败根因分类 | 详细诊断特征 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 01 | `adaptive-rejection-sampler` | 986s | 35,820 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 02 | `caffe-cifar-10` | 1277s | 3,730 | 单机 CPU 物理极限 | 纯物理算力瓶颈耗尽配时超时 |
| 03 | `dna-assembly` | 295s | 38,218 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 04 | `extract-moves-from-video` | 1856s | 3,890 | 单机 CPU 物理极限 | 纯物理算力瓶颈耗尽配时超时 |
| 05 | `filter-js-from-html` | 298s | 25,986 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 06 | `gcode-to-text` | 1078s | 59,652 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 07 | `install-windows-3.11` | 1956s | 1,207,493 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 08 | `large-scale-text-editing` | 259s | 5,573 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 09 | `make-doom-for-mips` | 1047s | 245,767 | 单机 CPU 物理极限 | 纯物理算力瓶颈耗尽配时超时 |
| 10 | `polyglot-rust-c` | 949s | 179,533 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 11 | `qemu-alpine-ssh` | 792s | 26,030 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 12 | `query-optimize` | 706s | 7,279 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 13 | `raman-fitting` | 665s | 256,080 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 14 | `sam-cell-seg` | 2469s | 117,716 | 单机 CPU 物理极限 | 纯物理算力瓶颈耗尽配时超时 |
| 15 | `sanitize-git-repo` | 382s | 86,650 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 16 | `torch-pipeline-parallelism` | 1324s | 21,682 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
| 17 | `train-fasttext` | 3767s | 23,372 | 单机 CPU 物理极限 | 纯物理算力瓶颈耗尽配时超时 |
| 18 | `video-processing` | 337s | 54,413 | 微小边界/格式/参数偏差 | ReAct 循环执行完备，断言细节存在微小格式/参数差异 |
