# Terminal-Bench 2.0 评测结果对比中心 (Evaluation Results Center)

本目录用于统一归档、追踪和对比 **原厂 Pi Agent** 与 **自研 My-Pi-Agent** 在 Terminal-Bench 2.0 基准测试下的实际表现。

---

## 📊 核心对比总榜 (Leaderboard Comparison)

- **基准测试集**：Terminal-Bench 2.0 (全量 89 题)
- **底层模型**：DeepSeek-V4.1-Flash (`deepseek/deepseek-chat`)
- **评测环境**：Docker Sandbox (Windows WSL2 / Linux Container)
- **原厂 Pi 进度**：已完成 **19 / 89** 题，通过 **1** 题，当前通过率 **5.3%**

| 任务 ID (Task ID) | 原厂 Pi Agent (Official) | 自研 My-Pi-Agent | 相对效率 (Tokens / Time) | 详细报告 |
|---|:---:|:---:|:---:|:---:|
| `adaptive-rejection-sampler` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#adaptive-rejection-sampler) |
| `break-filter-js-from-html` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#break-filter-js-from-html) |
| `build-cython-ext` | ✅ **PASSED** | *待评测 (Pending)* | 耗时 180s / 1269476 tok | [查看战报](./pi_official_terminal_bench_2.md#build-cython-ext) |
| `build-pmars` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#build-pmars) |
| `build-pov-ray` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#build-pov-ray) |
| `caffe-cifar-10` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 15s | [查看战报](./pi_official_terminal_bench_2.md#caffe-cifar-10) |
| `cancel-async-tasks` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 8s | [查看战报](./pi_official_terminal_bench_2.md#cancel-async-tasks) |
| `chess-best-move` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#chess-best-move) |
| `circuit-fibsqrt` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 2s | [查看战报](./pi_official_terminal_bench_2.md#circuit-fibsqrt) |
| `cobol-modernization` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 13s | [查看战报](./pi_official_terminal_bench_2.md#cobol-modernization) |
| `code-from-image` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 1s | [查看战报](./pi_official_terminal_bench_2.md#code-from-image) |
| `compile-compcert` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 13s | [查看战报](./pi_official_terminal_bench_2.md#compile-compcert) |
| `configure-git-webserver` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 14s | [查看战报](./pi_official_terminal_bench_2.md#configure-git-webserver) |
| `constraints-scheduling` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 13s | [查看战报](./pi_official_terminal_bench_2.md#constraints-scheduling) |
| `count-dataset-tokens` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 1s | [查看战报](./pi_official_terminal_bench_2.md#count-dataset-tokens) |
| `crack-7z-hash` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 14s | [查看战报](./pi_official_terminal_bench_2.md#crack-7z-hash) |
| `custom-memory-heap-crash` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 1s | [查看战报](./pi_official_terminal_bench_2.md#custom-memory-heap-crash) |
| `db-wal-recovery` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 13s | [查看战报](./pi_official_terminal_bench_2.md#db-wal-recovery) |
| `distribution-search` | ❌ **FAILED** | *待评测 (Pending)* | 耗时 13s | [查看战报](./pi_official_terminal_bench_2.md#distribution-search) |

---

## 📁 目录结构说明

- [`pi_official_terminal_bench_2.md`](./pi_official_terminal_bench_2.md)：**原厂 Pi 官方 Agent** 的评测记录与单题详报（基线 Baseline）。
- [`my_pi_agent_terminal_bench_2.md`](./my_pi_agent_terminal_bench_2.md)：**自研 My-Pi-Agent** 的评测记录与单题详报。
- [`comparison_matrix.md`](./comparison_matrix.md)：两者的**深度横向对比分析**（架构差异、Token 开销、工具调用效率、错误自愈能力）。
