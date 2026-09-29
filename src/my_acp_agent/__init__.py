"""my_acp_agent —— my-pi-agent 的 Agent Client Protocol (ACP) 适配层。

将 ``my_coding_agent`` 产品层包装为符合 ACP 规范的 Agent，使 Zed / Neovim 等
支持 ACP 的编辑器可以直接把 my-pi-agent 作为外部 Agent 驱动。

模块划分：
- ``events``：内核事件 → ACP ``session/update`` 通知的纯函数翻译；
- ``permissions``：``PermissionGate`` 的 ACP 反向请求桥接；
- ``agent``：``AcpAgent`` 协议实现（会话生命周期 / 提示词 / 模式切换）；
- ``server``：stdio 传输入口。
"""

from my_acp_agent.agent import AcpAgent

__all__ = ["AcpAgent"]
