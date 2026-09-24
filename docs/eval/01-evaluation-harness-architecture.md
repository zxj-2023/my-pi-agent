# 自动化评测系统架构与设计规范 (Evaluation Harness)

本文档已完整归档至统一规范目录：
- 完整技术设计提案请参阅：[docs/superpowers/specs/2026-09-24-evaluation-harness-design.md](../superpowers/specs/2026-09-24-evaluation-harness-design.md)

---

## 1. 核心定位
本子系统为 `my-pi-agent` 构建工业级对标评测能力，涵盖三大核心基准：
1. **SWE-bench Verified**（Python 500 / Mini 50 题真实开源仓库代码修复）
2. **SWE-bench Multilingual**（跨语言真实仓库问题修复）
3. **Terminal-Bench 2.0 / 2.1**（Docker 容器内真实 Linux 终端、系统运维与命令行交互全流程）

## 2. 关键架构设计
- **无侵入驱动**：复用 `CodingAgent.run` 无头模式，配合 `PermissionGate(mode="autonomous")` 全自主执行。
- **不可变事件遥测**：通过 `agent.subscribe` 挂载 `EvalTelemetryCollector`，收集 10 大核心指标（Pass@1, Tokens, Turn 轮数, Cost, 耗时, 工具错误率）。
- **环境安全隔离**：提供本地隔离工作区（用于 Mini 回归）与 Docker 沙箱（用于真实 SWE-bench / Terminal-bench）。
- **A/B 增量对比**：支持类似 `dsh-eval compare` 的版本性能对比与显著性分析。
