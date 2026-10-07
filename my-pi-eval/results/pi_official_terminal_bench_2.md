# 原厂 Pi Agent 评测报告 (Official Pi on Terminal-Bench 2.0)

- **框架版本**：`@earendil-works/pi-coding-agent` v1.0.4 (原版 Node.js / TypeScript 引擎)
- **评测驱动**：Harbor 0.24.0 (Scheme 2: 容器内安装型)
- **测试模型**：`DeepSeek-V4.1-Flash` (`deepseek/deepseek-chat`)
- **评测时间**：2026-03-23

---

## 任务详报

### 1. `build-cython-ext`

#### 任务背景
- **难度**：中高难度 (C/Python 混合编译 + 兼容性重构)
- **目标**：在锁定 NumPy 2.3.0 的现代 Python 环境下，为拓扑分析库 `pyknotid` 编译生成 4 个 Cython C 扩展（`.so` 动态链接库），修复所有因依赖版本过新导致的兼容性破损，确保官方 upstream 单元测试全部通过。
- **环境**：Ubuntu 容器，Python 3.13，NumPy 2.3.0。

#### 评测结果与裁判输出
- **最终评定**：✅ **PASSED (100% 满分通过)**
- **官方奖励分 (reward.txt)**：`1.0`
- **验证集通过率**：`11 / 11` (100%)

```text
=========================== short test summary info ============================
PASSED tests/test_outputs.py::test_numpy_version            (NumPy 2.3.0 锁定未被篡改)
PASSED tests/test_outputs.py::test_repo_cloned              (Git 仓库完整性检查)
PASSED tests/test_outputs.py::test_pyknotid_core_import     (核心模块成功载入)
PASSED tests/test_outputs.py::test_chelpers_cython_extension    (C 动态链接库编译验证 1)
PASSED tests/test_outputs.py::test_ccomplexity_cython_extension (C 动态链接库编译验证 2)
PASSED tests/test_outputs.py::test_cinvariants_cython_extension (C 动态链接库编译验证 3)
PASSED tests/test_outputs.py::test_chelpers                 (C 扩展功能计算测试)
PASSED tests/test_outputs.py::test_ccomplexity              (高阶拓扑不变量数学计算)
PASSED tests/test_outputs.py::test_cinvariants_python_vs_cython (Cython 与 Python 结果一致性)
PASSED tests/test_outputs.py::test_example_usage            (官方 README 示例验证)
PASSED tests/test_outputs.py::test_pyknotid_repository_tests (全套 upstream 单元测试)
============================== 11 passed in 8.64s ==============================
```

#### 执行轨迹核心亮点
1. **构建系统排障**：发现 PEP 517 build isolation 会静默丢弃 Cython C 扩展，果断采用 `pip install -e . --no-build-isolation`。
2. **多文件外科手术式修改**：
   - 修复 NumPy 2.0 移除的 31 处废弃别名 (`np.float`, `np.int`, `np.bool`, `np.complex`, `np.long`)，涉及 12 个源码文件；
   - 修复 Python 3.9+ 迁移 `from math import gcd`；
   - 修复 `planarity 1.0` 的属性名变更。
3. **主动自检机制**：做完后自己写 Python 正则脚本全盘遍历项目 `.py` 和 `.pyx` 文件，比对是否存在任何遗留的 NumPy 2.3 弃用函数，并在容器内成功验证了 pytest。

#### 指标与开销统计
- **做题时间**：约 3 分钟（容器冷启动拉取环境约 2.5 分钟）
- **Token 消耗**：约 41,626 tokens
- **费用**：约 0.10 元人民币 ($0.015)
- **工具调用轮次**：约 15 轮
