# my-pi-eval: Harbor & Terminal-Bench 2.0 评测套件

`my-pi-eval` 是专为 `my-pi-agent` 打造的官方基准评测适配与调度子系统，基于标准 **Harbor Framework** 协议实现，主要用于在 **Terminal-Bench 2.0**（以及后续的 SWE-bench）真实沙箱中全自动评测 Agent 的终端解题能力。

---

## 核心设计与架构

1. **官方标准 BaseAgent 适配**：实现 `MyPiAgent`（继承自 `harbor.agents.base.BaseAgent`），可直接被 Harbor 官方 CLI (`harbor run`) 加载与调用。
2. **宿主编排型（Scheme 1: Host-Orchestrated）**：Agent 核心与大模型请求运行在宿主机 Python 3.11 环境中，通过 `HarborToolRegistry` 将 7 大核心工具直连 Docker 容器沙箱，**实现对评测环境的零污染与秒级启动**。
3. **高保真工具桥接**：
   - `bash`: 容器内隔离执行、超时熔断（默认 120s）与 50KB 输出安全截断。
   - `read`: 容器内文件按 offset/limit 行号精准分片。
   - `write`: 自动规范化换行符（CRLF ➔ LF），防止 Windows 宿主导致 Linux 容器脚本损坏。
   - `edit`: 宿主机内存执行严格的单义性校验与外科手术式代码替换，原子写回沙箱。
   - `ls` / `grep` / `find`: 容器内实时文件系统检索。
4. **指标与轨迹自动聚合**：自动追踪 Prompt Tokens、Completion Tokens、Cache Read Tokens、耗时及状态，输出标准 `metrics.json`。

---

## 运行前准备（Prerequisites）

1. **Docker Desktop**：
   评测任务依赖 Docker 启动容器沙箱。请确保 Windows Docker Desktop 处于运行状态。
   可使用自带 Doctor 进行预检：
   ```bash
   python -m my_pi_eval.cli --check
   ```

2. **专属评测 `.env` 凭证配置（严禁读取本地 auth.json）**：
   为确保基准评测环境与开发者日常环境完全隔离，`my-pi-eval` **严格禁止读取本地 `~/.my-pi-agent/auth.json`**，而是专门在 `my-pi-eval/.env` 中独立配置 API Key。
   
   在 `my-pi-eval/` 目录下创建 `.env`（可参考同目录下的 `.env.example`）：
   ```env
   # my-pi-eval/.env
   DEEPSEEK_API_KEY=sk-xxxx
   # 可选自定义接口地址（默认官方 https://api.deepseek.com）
   DEEPSEEK_BASE_URL=https://api.deepseek.com
   ```
   *(注：`my-pi-eval/.env` 已被 Git 自动忽略，且主项目运行完全不加载此文件，保证工作区无污染与凭据隔离)*

---

## 评测执行指南

### 1. 单任务冒烟测试（以 `build-cython-ext` 为例）

```bash
# 方式 A：使用 my-pi-eval CLI
python -m my_pi_eval.cli -p D:/code/python/agent-eval/terminal-bench-2/build-cython-ext -m deepseek/deepseek-chat

# 方式 B：使用 Harbor 官方原生 CLI
harbor run \
  -p D:/code/python/agent-eval/terminal-bench-2/build-cython-ext \
  --agent-import-path my_pi_eval.agent:MyPiAgent \
  -m deepseek/deepseek-chat
```

### 2. 多任务批量评测与并发控制

```bash
# 并发跑 4 个沙箱容器
harbor run \
  -p D:/code/python/agent-eval/terminal-bench-2 \
  --agent-import-path my_pi_eval.agent:MyPiAgent \
  -m deepseek/deepseek-chat \
  -n 4
```

### 3. 查看评测报告与轨迹

评测完成后，Harbor 与 `my-pi-eval` 会在运行目录输出详细记录：
- `verifier/reward.txt`：测试判定结果（`1` 为通过，`0` 为未通过）。
- `agent/metrics.json`：该题消耗的 Token 数量、耗时与报错。
- `agent/session.jsonl`：Agent 与沙箱互动的完整 ReAct 对话树与工具轨迹。

---

## 单元测试与验证

套件包含 15 个针对沙箱工具桥接、CRLF 规范化、指标汇总与 CLI 预检的离线单元测试：

```bash
uv run python -m pytest tests/eval/ -v
```
