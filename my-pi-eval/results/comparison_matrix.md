# 框架横向深度对比矩阵 (Comparative Analysis Matrix)

本项目用于全方位对比 **原厂 Pi Agent (Node.js/TS)** 与 **自研 My-Pi-Agent (Python)** 在同一基准试卷（Terminal-Bench 2.0）和同一模型（DeepSeek-V4.1-Flash）下的表现。

---

## 1. 架构与工程特性对比

| 维度 | 原厂 Pi Agent (`@earendil-works/pi-coding-agent`) | 自研 My-Pi-Agent (`my-pi-agent`) | 理论优势对比 |
|---|---|---|---|
| **评测模式** | **Scheme 2 (容器内安装型)**<br>Harbor 在测试容器内在线下载 Node.js 并 `npm install` 安装 Pi | **Scheme 1 (宿主机驱动型)**<br>Agent 留在宿主机，仅通过 BaseEnvironment 管道驱动容器 | **My-Pi-Agent 胜出**：容器完全免安装任何 Node 环境，冷启动从 2.5 分钟缩减至 < 2 秒 |
| **语言栈** | TypeScript / Node.js | Python 3.12+ (纯微内核 ReAct + Pydantic) | 语言统一，与 AI/Eval 评测栈 100% 契合 |
| **工具映射** | 容器内原生 bash/fs 进程调用 | `HarborToolRegistry` 桥接 7 大工作区工具至容器 Docker API | 精细化错误拦截，防止沙箱逃逸 |
| **Token 管理** | 纯客户端 session 统计 | 4 级上下文压缩管线 (L1-L4) + 实时 TokenTracker | 自研框架具备多轮超长会话防溢出保护 |
| **凭据隔离** | 需向容器透传环境变量 API Key | 宿主机本地读取 `my-pi-eval/.env`，API Key 绝不流入测试容器 | **更安全**：即使测试代码被恶意篡改，也无法窃取容器外的 API Key |

---

## 2. Terminal-Bench 2.0 战绩对比一览

| 任务名称 (Task) | 任务类别 | 原厂 Pi (DeepSeek) | My-Pi-Agent (DeepSeek) | 胜出方 / 分析 |
|---|---|:---:|:---:|---|
| `build-cython-ext` | 依赖编译 & C扩展 | ✅ **PASSED (11/11)** | *待跑* | 原厂表现稳健，无失误完成 |
| *待扩充后续题集...* | - | - | - | - |

---

## 3. 评测打榜工作流

后续每次评测新任务时：
1. **先跑原厂 Pi**：记录基线分数、Token 消耗与解题思路到 `pi_official_terminal_bench_2.md`；
2. **再跑自研 My-Pi-Agent**：运行命令，记录数据到 `my_pi_agent_terminal_bench_2.md`；
3. **在对比矩阵中比对**：
   - 是否通过？
   - 消耗的 Token 是多是少？
   - 解决同一问题的步数（Turn 次数）谁更少更精准？
   - 发现不足后，回到 `src/my_agent_core` 或 `src/my_coding_agent` 进行针对性优化迭代。
