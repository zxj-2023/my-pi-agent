# my-pi-eval: Agent 自动化评测系统

`my-pi-eval` 是专为 `my-pi-agent` 构建的自动化评测与基准测试套件，对标工业界标准（DeepSeek Harness `dsh-eval`、Pi `pi-terminal-bench`、SWE-bench Official Harness）。

---

## 目录结构设计

```text
my-pi-eval/
├── README.md                  # 本评测套件说明文档
├── configs/                   # 评测配置与基准任务声明
│   ├── swe_bench_verified.yaml# SWE-bench Verified 评测配置
│   ├── swe_bench_multi.yaml   # SWE-bench Multilingual 跨语言配置
│   ├── terminal_bench.yaml    # Terminal-Bench 2.1 终端运维配置
│   └── mini_regression.yaml   # 20 题轻量快速回归集配置
├── datasets/                  # 本地测试用例与轻量级 benchmark 数据
│   └── fixtures/              # 本地单元/单单测验证环境
├── src/                       # 评测系统核心 Python 实现
│   ├── __init__.py
│   ├── adapter.py             # CodingAgent 无头驱动适配器 (Zero Harness Tax)
│   ├── telemetry.py           # 10 项标准化指标实时事件流收集器
│   ├── runner.py              # 并发任务调度与沙箱环境编排器 (Worktree/Docker)
│   ├── grader.py              # 判定器 (SWE-bench Patch 测试 / Terminal-bench check.sh)
│   └── reporter.py            # 结果看板与 A/B 差异分析 (Markdown & JSON)
├── reports/                   # 评测运行历史与产物 (JSON 原始轨迹 + Markdown 报告)
└── run.py                     # CLI 快速启动入口
```

---

## 支持的核心评测集

1. **SWE-bench Verified**：
   - 真实开源 Python 库（Django, SymPy, Pytest 等）500 题与 Mini-SWE 抽样。
   - 检验跨文件检索、代码修改与隐藏单元测试修复能力。
2. **SWE-bench Multilingual**：
   - 跨语言（TypeScript, Go, Java, Rust, C++）工程代码库修复评测。
3. **Terminal-Bench 2.0 / 2.1**：
   - 纯 Docker Linux 终端运维、依赖编译与系统级复杂任务交互。

---

## 核心设计规范

详细技术设计规范请参阅：
- [`docs/eval/01-evaluation-harness-architecture.md`](../docs/eval/01-evaluation-harness-architecture.md)
- [`docs/superpowers/specs/2026-09-24-evaluation-harness-design.md`](../docs/superpowers/specs/2026-09-24-evaluation-harness-design.md)
