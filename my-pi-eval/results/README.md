# Terminal-Bench 2.0 评测结果对比中心 (Evaluation Results Center)

本目录用于统一归档、追踪和对比 **原厂 Pi Agent** 与 **自研 My-Pi-Agent** 在 Terminal-Bench 2.0 基准测试下的实际表现。

---

## 📊 核心对比总榜 (Leaderboard Comparison)

- **基准测试集**：Terminal-Bench 2.0 (89 题真实 Linux / 终端任务)
- **底层模型**：DeepSeek-V4.1-Flash (`deepseek/deepseek-chat`)
- **评测环境**：Docker Sandbox (Windows WSL2 / Linux Container)

| 任务 ID (Task ID) | 原厂 Pi Agent (Official) | 自研 My-Pi-Agent | 相对效率 (Tokens / Time) | 详细报告 |
|---|:---:|:---:|:---:|:---:|
| `build-cython-ext` | ✅ **PASSED (11/11)** | *待评测 (Pending)* | 原厂耗时 ~3m / 41K tok | [查看报告](./pi_official_terminal_bench_2.md#build-cython-ext) |
| *（待跑后续任务...）* | - | - | - | - |

---

## 📁 目录结构说明

- [`pi_official_terminal_bench_2.md`](./pi_official_terminal_bench_2.md)：**原厂 Pi 官方 Agent** 的评测记录与单题详报（基线 Baseline）。
- [`my_pi_agent_terminal_bench_2.md`](./my_pi_agent_terminal_bench_2.md)：**自研 My-Pi-Agent** 的评测记录与单题详报。
- [`comparison_matrix.md`](./comparison_matrix.md)：两者的**深度横向对比分析**（架构差异、Token 开销、工具调用效率、错误自愈能力）。

---

## 🛠️ 评测方法与复现指令

### 1. 运行原厂 Pi 评测
```powershell
cd D:\code\python\agent-eval\pi-terminal-bench
.venv\Scripts\harbor.exe run `
  -p D:\code\python\agent-eval\terminal-bench-2\<task_id> `
  -a pi `
  -m deepseek/deepseek-chat
```

### 2. 运行自研 My-Pi-Agent 评测
```powershell
cd D:\code\python\my-pi-agent
python -m my_pi_eval.cli -p D:/code/python/agent-eval/terminal-bench-2/<task_id>
```
