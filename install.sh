#!/usr/bin/env sh
# my-pi-agent one-line installer for Linux & macOS
# Usage: curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash

set -e

INSTALL_DIR="${HOME}/.my-pi-agent"
BIN_DIR="${INSTALL_DIR}/bin"

echo "=== 安装 my-pi-agent ==="

# 1. 检查基础工具
if ! command -v node >/dev/null 2>&1; then
    echo "提示: 未检测到 Node.js，my-pi-agent 交互界面需要 Node.js (>=18)。"
    echo "请先安装 Node.js: https://nodejs.org"
fi

mkdir -p "${BIN_DIR}"

# 2. 生成本地全局可执行文件软链接或启动包装脚本
WRAPPER="${BIN_DIR}/my-pi-agent"
cat <<'EOF' >"${WRAPPER}"
#!/usr/bin/env sh
DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 优先探测系统 npx / node 全局包或本地环境
if command -v my-pi-agent >/dev/null 2>&1 && [ "$(command -v my-pi-agent)" != "$0" ]; then
    exec "$(command -v my-pi-agent)" "$@"
fi

if [ -f "${DIR}/tui/bin/my-agent.js" ]; then
    exec node "${DIR}/tui/bin/my-agent.js" "$@"
fi

exec npx my-pi-agent "$@"
EOF

chmod +x "${WRAPPER}"

# 3. 环境变量 PATH 配置检查
SHELL_NAME="$(basename "${SHELL:-sh}")"
RC_FILE=""

case "${SHELL_NAME}" in
zsh)
    RC_FILE="${HOME}/.zshrc"
    ;;
bash)
    if [ -f "${HOME}/.bash_profile" ]; then
        RC_FILE="${HOME}/.bash_profile"
    else
        RC_FILE="${HOME}/.bashrc"
    fi
    ;;
*)
    RC_FILE="${HOME}/.profile"
    ;;
esac

if [ -n "${RC_FILE}" ] && [ -f "${RC_FILE}" ]; then
    if ! grep -q "\.my-pi-agent/bin" "${RC_FILE}"; then
        echo "" >>"${RC_FILE}"
        echo '# my-pi-agent PATH' >>"${RC_FILE}"
        echo 'export PATH="${HOME}/.my-pi-agent/bin:${PATH}"' >>"${RC_FILE}"
        echo "✓ 已将 ${BIN_DIR} 添加到 ${RC_FILE}"
    fi
fi

echo "✓ my-pi-agent 安装就绪: ${WRAPPER}"
echo "提示: 重启终端或执行 'source ${RC_FILE}' 后即可直接敲 'my-pi-agent' 体验！"
