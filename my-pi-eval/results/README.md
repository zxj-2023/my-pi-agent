# Terminal-Bench 2.1 评测结果中心 (Evaluation Results Center)

本目录用于统一归档、追踪和对比 **自研 MyPiAgent** 与 **原厂 Pi 官方 Agent** 在 Terminal-Bench 2.1 基准测试下的最终全量评测表现。

---

## 🏆 核心终局总榜 (Head-to-Head Overview)

- **基准测试集**：Terminal-Bench 2.1 (全量 89 题 Linux 终端运维、深度学习与系统逆向赛题)
- **底座大模型**：统一采用 DeepSeek-V4.1 (`deepseek/deepseek-chat` / DS-V4.1-Flash)
- **评测沙箱**：Docker Sandbox (Windows WSL2 宿主驱动)

| 核心指标 | 自研 MyPiAgent | 原厂 Pi 官方 Agent | 对比与胜出分析 |
| :--- | :---: | :---: | :--- |
| **89 题全量通过题数** | **71 道 (79.78%)** | **72 道 (80.90%)** | 工业基准高度逼近（仅差 1 题） |
| **85 题常规有效通过题数** | **71 道 (83.53%)** 🏆 | **72 道 (84.71%)** | 均展现世界级终端自愈能力 |
| **双胜题目数 (两边均通过)** | **67 道** | 67 道 | 覆盖绝大多数 Linux 系统工程题 |
| **MyPiAgent 独占胜出赛题** | **6 道** 🌟 | - | 自研 Agent 斩获满分，官方 Pi 彻底折戟 |
| **官方 Pi 独占胜出赛题** | - | **7 道** | 官方 Pi 满分，自研 Agent 格式或微差落后 |
| **双负赛题 (两边均未过)** | **11 道** | 11 道 | 包含单机物理算力极限与上游脆弱断言 |
| **全量 Token 与缓存开销** | **41,737,271 Tokens** (KV-Cache 82,273,152) | **93,322,290 Tokens** | 自研 Agent 借助离散 Epoch 块级压缩，Token 开销仅为原厂的 44.7% |
| **全量评测总开销** | **$4.62 美元** (约 33.5 元) | ~$10.5 美元 | 极致经济高效 |

---

## 🌟 自研 MyPiAgent 独占胜出大题 (官方 Pi 失败)

在完全一致的物理环境与模型下，自研 Agent 在以下 6 道高难度赛题上斩获 1.0 满分，而官方 Pi 彻底失败：
1. **`make-mips-interpreter`**：纯手写 MIPS 寄存器机与指令集模拟器（自研 Agent 鏖战 50 分钟单步调试满分通过，官方 Pi 超时失败）；
2. **`cancel-async-tasks`**：高并发异步任务优雅取消状态机（自研 Agent 满分通过，官方 Pi 失败）；
3. **`polyglot-c-py`**：编写同时符合 C 语法与 Python 语法的同源文件（自研 Agent 满分通过，官方 Pi 失败）；
4. **`pytorch-model-cli`**：PyTorch 模型 CLI 动态装配推理（自研 Agent 满分通过，官方 Pi 失败）；
5. **`git-multibranch`**：多分支自动化部署与 Hook 脚本调度（自研 Agent 满分通过，官方 Pi 失败）；
6. **`model-extraction-relu-logits`**：深度学习模型网络权重逆向提取（自研 Agent 满分通过，官方 Pi 失败）。

---

## 📁 核心评测报告索引

- 📄 [`my_pi_agent_terminal_bench_2.md`](./my_pi_agent_terminal_bench_2.md)：**自研 MyPiAgent 终局战报**（71 道满分赛题英雄榜、18 道未过题目根因归类、41.7M Tokens 详细账单）。
- 📄 [`pi_official_terminal_bench_2.md`](./pi_official_terminal_bench_2.md)：**原厂 Pi 官方 Agent 终局战报**（72 胜官方基准数据）。
- 📄 [`comparison_matrix.md`](./comparison_matrix.md)：**89 题逐题全量横向对比矩阵**（两边详细状态对比、独占胜出分析与技术反思）。
- 📊 [`my_pi_agent_progress.json`](./my_pi_agent_progress.json)：自研 Agent 89 题全量真实机器可读评测进度记录（0 Token 盲区彻底消除）。
- 📊 [`official_pi_progress.json`](./official_pi_progress.json)：原厂 Pi 89 题真实机器可读评测进度记录。
