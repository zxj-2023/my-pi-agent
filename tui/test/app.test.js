import test from "node:test";
import assert from "node:assert/strict";
import { AgentApp } from "../dist/app.js";

test("AgentApp initializes component tree properly", () => {
  const app = new AgentApp({ workspace: "." });
  assert.ok(app);
});

test("AgentApp handles agent events without throwing", () => {
  const app = new AgentApp({ workspace: "." });

  // 模拟发送消息
  app.handleAgentEvent({
    type: "message_update",
    message: { role: "assistant", content: "hello world" },
    delta: "hello world",
    reasoning_delta: "deep thinking",
  });

  // 模拟工具开始执行
  app.handleAgentEvent({
    type: "tool_execution_start",
    toolCallId: "call_read_1",
    toolName: "read",
    args: { path: "src/app.ts" },
  });
  assert.equal(app["activeTools"].has("call_read_1"), true);
  assert.equal(app["toolStartTimes"].has("call_read_1"), true);

  // 模拟工具更新
  app.handleAgentEvent({
    type: "tool_execution_update",
    toolCallId: "call_read_1",
    toolName: "read",
    args: { path: "src/app.ts" },
    partialResult: null,
  });

  // 模拟工具完成
  app.handleAgentEvent({
    type: "tool_execution_end",
    toolCallId: "call_read_1",
    toolName: "read",
    result: "export class AgentApp {}",
    isError: false,
  });
  const toolComp = app["activeTools"].get("call_read_1");
  assert.ok(toolComp);
  assert.equal(toolComp.finished, true);
  assert.equal(toolComp.elapsed >= 0, true);
  assert.equal(app["toolStartTimes"].has("call_read_1"), false);

  // 模拟未正常闭合的工具 (测试中断自动闭合机制)
  app.handleAgentEvent({
    type: "tool_execution_start",
    toolCallId: "call_read_2",
    toolName: "read",
    args: { path: "src/calc.py" },
  });
  const tool2 = app["activeTools"].get("call_read_2");
  assert.equal(tool2.finished, false);

  // 模拟 agent 结束 -> 应当自动闭合未完成工具
  app.handleAgentEvent({
    type: "agent_end",
    iterations: 1,
    stop_reason: "end_turn",
  });
  assert.equal(tool2.finished, true);
});

test("AgentApp mounts autocomplete provider with slash commands and @ file references", async () => {
  const app = new AgentApp({ workspace: "." });
  const provider = app.editor.autocompleteProvider;
  assert.ok(provider);

  // 1. 测试 / 斜杠命令联想补全
  const slashSuggestions = await provider.getSuggestions(["/mod"], 0, 4, {
    signal: new AbortController().signal,
  });
  assert.ok(slashSuggestions);
  assert.ok(
    slashSuggestions.items.some(
      (i) => i.value === "model" || i.label === "model",
    ),
  );

  // 2. 测试 @ 文件路径模糊匹配联想
  const fileSuggestions = await provider.getSuggestions(["@package"], 0, 8, {
    signal: new AbortController().signal,
  });
  assert.ok(fileSuggestions);
  assert.ok(
    fileSuggestions.items.some((i) => i.value.includes("package.json")),
  );
});

test("AgentApp handles slash commands (/clear, /help, /steer, /followup) locally without throwing", async () => {
  const app = new AgentApp({ workspace: "." });

  let capturedSteer = "";
  let capturedFollowup = "";
  app["client"].steer = async (msg) => {
    capturedSteer = msg;
  };
  app["client"].followup = async (msg) => {
    capturedFollowup = msg;
  };
  app["client"].sendRequest = async (method, params) => {
    if (method === "login") {
      return {
        status: "ok",
        message: `成功保存 ${params.provider.toUpperCase()}_API_KEY`,
      };
    }
    return { status: "ok" };
  };

  // 1. /help 命令
  await app.handleUserSubmit("/help");
  assert.equal(app.chatContainer.children.length, 2);
  const helpText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(helpText.includes("/session"));
  assert.ok(helpText.includes("/settings"));
  assert.ok(helpText.includes("/login"));

  // 2. /clear 命令
  await app.handleUserSubmit("/clear");
  assert.equal(app.chatContainer.children.length, 0);

  // 3. /steer 命令成功分支
  await app.handleUserSubmit("/steer 优先写测试");
  assert.equal(capturedSteer, "优先写测试");

  // 4. /followup 命令成功分支
  await app.handleUserSubmit("/followup 检查边界");
  assert.equal(capturedFollowup, "检查边界");

  // 5. 空参数 /steer 与 /followup
  await app.handleUserSubmit("/steer");
  await app.handleUserSubmit("/followup");

  // 6. /model 与 /quota 命令
  await app.handleUserSubmit("/model gemini-3.8-flash");
  await app.handleUserSubmit("/quota");

  // 7. /session, /settings 与 /login 命令
  await app.handleUserSubmit("/session");
  const sessionText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(sessionText.includes("Session Info"));

  await app.handleUserSubmit("/settings");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  await app.handleUserSubmit("/login");
  assert.ok(app["activeSelectorComponent"]);
  // 按 Esc 取消并关闭选择器
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  await app.handleUserSubmit("/login deepseek sk-test-key-123");
  const loginSuccessText = app.chatContainer.children
    .at(-1)
    .render(120)
    .join("\n");
  assert.ok(loginSuccessText.includes("DEEPSEEK_API_KEY"));

  // 8. 测试在 isBusy 期间拦截 /clear
  app["isBusy"] = true;
  const countBefore = app.chatContainer.children.length;
  await app.handleUserSubmit("/clear");
  assert.ok(
    app.chatContainer.children.length > countBefore,
    "Should reject /clear when busy and keep session intact",
  );
  app["isBusy"] = false;

  // 9. 恢复后正常清空
  await app.handleUserSubmit("/clear");
  assert.equal(app.chatContainer.children.length, 0);

  // 10. 未知命令
  await app.handleUserSubmit("/unknown_cmd");
  assert.ok(app.chatContainer.children.length > 0);
});

test("AgentApp handles new slash commands (/new, /resume, /name, /compact, /tree, /fork, /clone, /thinking, /logout, /reload, /trust)", async () => {
  const app = new AgentApp({ workspace: "." });

  app["client"].sendRequest = async (method, params) => {
    if (method === "session_new") {
      return {
        status: "ok",
        session_id: "sid-new-123",
        session_file: "/tmp/sid-new-123.jsonl",
      };
    }
    if (method === "session_list") {
      return {
        status: "ok",
        sessions: [
          {
            id: "s1",
            name: "历史测试一",
            modified: 1710000000,
            message_count: 8,
            path: "/tmp/s1.jsonl",
          },
          {
            id: "s2",
            name: "历史测试二",
            modified: 1710001000,
            message_count: 3,
            path: "/tmp/s2.jsonl",
          },
        ],
      };
    }
    if (method === "session_resume") {
      return { status: "ok", session_id: params?.session_id || "s1" };
    }
    if (method === "session_name") {
      return { status: "ok", name: params?.name || "测试会话名" };
    }
    if (method === "session_compact") {
      return {
        status: "ok",
        tokens_before: 12000,
        tokens_after: 3500,
        summary: "压缩完成测试摘要",
      };
    }
    if (method === "session_tree") {
      return {
        status: "ok",
        nodes: [
          {
            id: "n1",
            parent_id: null,
            role: "user",
            preview: "user prompt 1",
            is_leaf: false,
            is_active_path: true,
          },
          {
            id: "n2",
            parent_id: "n1",
            role: "assistant",
            preview: "assistant answer 1",
            is_leaf: false,
            is_active_path: true,
          },
          {
            id: "n3",
            parent_id: "n2",
            role: "user",
            preview: "user prompt 2",
            is_leaf: true,
            is_active_path: true,
          },
        ],
        active_leaf_id: "n3",
        root_id: "n1",
      };
    }
    if (method === "session_fork") {
      return {
        status: "ok",
        new_session_id: "forked-s4",
        session_file: "/tmp/forked.jsonl",
        prompt_text: "user prompt 2",
      };
    }
    if (method === "session_clone") {
      return {
        status: "ok",
        new_session_id: "cloned-s5",
        session_file: "/tmp/cloned.jsonl",
      };
    }
    if (method === "models_list") {
      return {
        status: "ok",
        models: [
          {
            id: "deepseek-chat",
            provider: "deepseek",
            name: "DeepSeek V3",
            contextWindow: 64000,
          },
        ],
      };
    }
    if (method === "model_switch") {
      return { status: "ok", model: params?.model || "deepseek-chat" };
    }
    if (method === "thinking_set") {
      return { status: "ok", level: params?.level || "high" };
    }
    if (method === "auth_logout") {
      return {
        status: "ok",
        provider: params?.provider || "openai",
        removed: true,
      };
    }
    if (method === "resource_reload") {
      return { status: "ok", summary: "Reloaded 8 skills, 4 templates" };
    }
    if (method === "trust_set") {
      return {
        status: "ok",
        path: "/test/workspace",
        trusted: params?.trusted,
        decision: params?.trusted ? "trusted" : "untrusted",
      };
    }
    return { status: "ok" };
  };

  // 1. /new
  await app.handleUserSubmit("/new");
  const newText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(newText.includes("sid-new-123"));

  // 2. /resume (无参 -> 调起交互选择器)
  await app.handleUserSubmit("/resume");
  assert.ok(app["activeSelectorComponent"]);
  // 模拟按 Esc 取消并退出选择器
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 3. /resume s1 (带参 -> session_resume)
  await app.handleUserSubmit("/resume s1");
  const resumeText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(resumeText.includes("s1"));

  // 4. /name
  await app.handleUserSubmit("/name 重命名测试");
  const nameText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(nameText.includes("重命名测试"));

  // 5. /compact
  await app.handleUserSubmit("/compact 聚焦总结核心代码");
  const compactText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(compactText.includes("12,000"));
  assert.ok(compactText.includes("[compaction]"));

  // 6. /tree (无参 -> 调起 TreeSelector)
  await app.handleUserSubmit("/tree");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 7. /fork
  await app.handleUserSubmit("/fork n1");
  const forkText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(forkText.includes("forked-s4"));

  // 8. /clone
  await app.handleUserSubmit("/clone");
  const cloneText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(cloneText.includes("cloned-s5"));

  // 9. /thinking
  await app.handleUserSubmit("/thinking high");
  const thinkingText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(thinkingText.includes("high"));

  // 10. /logout
  await app.handleUserSubmit("/logout openai");
  const logoutText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(logoutText.includes("openai"));

  // 11. /reload
  await app.handleUserSubmit("/reload");
  const reloadText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(reloadText.includes("Reloaded 8 skills"));

  // 12. /trust
  await app.handleUserSubmit("/trust true");
  const trustText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(trustText.includes("trusted"));

  // 13. /login (无参 -> 调起 LoginSelector)
  await app.handleUserSubmit("/login");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 14. /model (无参 -> 调起 ModelSelector)
  await app.handleUserSubmit("/model");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 15. /settings (无参 -> 调起 SettingsSelector)
  await app.handleUserSubmit("/settings");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 16. /fork (无参 -> 调起 UserMessageSelector)
  await app.handleUserSubmit("/fork");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 17. /logout (无参 -> 调起 LogoutSelector)
  await app.handleUserSubmit("/logout");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);

  // 18. /theme (无参 -> 调起 ThemeSelector)
  await app.handleUserSubmit("/theme");
  assert.ok(app["activeSelectorComponent"]);
  app["activeSelectorComponent"].handleInput("\x1b");
  assert.equal(app["activeSelectorComponent"], undefined);
});

test("AgentApp handles shell macro (!cmd, !!cmd) and switches border color on !", async () => {
  const app = new AgentApp({ workspace: "." });

  // 1. 测试输入框以 ! 开头变色
  app["editor"].onChange("!ls");
  const fnYellow = app["editor"].borderColor;
  app["editor"].onChange("ls");
  const fnNormal = app["editor"].borderColor;
  assert.notEqual(
    fnYellow,
    fnNormal,
    "Border color function should change in Bash mode",
  );

  // 2. 测试 !cmd (入上下文)
  let lastShellExec = null;
  app["client"].sendRequest = async (method, params) => {
    if (method === "shell_exec") {
      lastShellExec = params;
      return { status: "ok", output: "file1.py\nfile2.py", exit_code: 0 };
    }
    return { status: "ok" };
  };

  await app.handleUserSubmit("!git status");
  assert.ok(lastShellExec);
  assert.equal(lastShellExec.command, "git status");
  assert.equal(lastShellExec.exclude_from_context, false);
  const outText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(outText.includes("file1.py"));
  assert.ok(outText.includes("已加入上下文"));

  // 3. 测试 !!cmd (静默执行，不入上下文)
  lastShellExec = null;
  await app.handleUserSubmit("!!python -V");
  assert.ok(lastShellExec);
  assert.equal(lastShellExec.command, "python -V");
  assert.equal(lastShellExec.exclude_from_context, true);
  const silentText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(silentText.includes("静默执行，未加入上下文"));

  // 4. 空命令 !
  await app.handleUserSubmit("!");
  const warnText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(warnText.includes("请输入要执行的本地 Shell 命令"));
});

test("AgentApp expands macros (/skill: and /<template>) before submitting prompt", async () => {
  const app = new AgentApp({ workspace: "." });

  let capturedPrompt = "";
  app["client"].prompt = async (text) => {
    capturedPrompt = text;
  };

  app["client"].sendRequest = async (method, params) => {
    if (method === "macro_expand") {
      if (params?.text?.startsWith("/skill:deploy")) {
        return {
          status: "ok",
          expanded: true,
          text: '<skill name="deploy">\n# Deploy\n</skill>\nprod --dry-run',
        };
      }
      if (params?.text?.startsWith("/review")) {
        return {
          status: "ok",
          expanded: true,
          text: "Review target: src/app.ts",
        };
      }
      return { status: "ok", expanded: false, text: params?.text };
    }
    return { status: "ok" };
  };

  // 1. /skill: 宏展开
  await app.handleUserSubmit("/skill:deploy prod --dry-run");
  assert.ok(capturedPrompt.includes('<skill name="deploy">'));
  assert.ok(capturedPrompt.includes("prod --dry-run"));

  // 2. /<template> 宏展开
  await app.handleUserSubmit("/review src/app.ts");
  assert.equal(capturedPrompt, "Review target: src/app.ts");

  // 3. 未识别的命令宏 -> 回退为未知命令提示
  await app.handleUserSubmit("/non_existent_macro");
  const unknownText = app.chatContainer.children.at(-1).render(120).join("\n");
  assert.ok(unknownText.includes("暂未在当前内核模式下启用"));
});

test("AgentApp renders session history messages (user, assistant, tool execution) on session_resume", async () => {
  const app = new AgentApp({ workspace: "." });

  app["client"].sendRequest = async (method, _params) => {
    if (method === "session_resume") {
      return {
        status: "ok",
        session_id: "resumed-session-999",
        session_name: "历史会话999",
        messages: [
          { role: "user", content: "请帮我读取 package.json" },
          {
            role: "assistant",
            content: "好的，我正在读取文件内容：",
            metadata: {
              thinking: "让我思考一下使用 read 工具...",
              tool_calls: [
                {
                  id: "call-1",
                  function: {
                    name: "read",
                    arguments: '{"path": "package.json"}',
                  },
                },
              ],
            },
          },
          {
            role: "tool",
            content: '{"name": "my-agent-tui", "version": "0.1.0"}',
            metadata: {
              tool_call_id: "call-1",
              tool_name: "read",
              is_error: false,
            },
          },
          {
            role: "assistant",
            content: "读取完成，版本号是 0.1.0。",
          },
        ],
      };
    }
    return { status: "ok" };
  };

  await app.handleUserSubmit("/resume resumed-session-999");

  // 验证 chatContainer 渲染了所有历史组件
  assert.ok(app.chatContainer.children.length >= 4);

  const renderedAll = app.chatContainer.children
    .map((c) => (c.render ? c.render(120).join("\n") : ""))
    .join("\n");

  assert.ok(renderedAll.includes("resumed-session-999"));
  assert.ok(renderedAll.includes("请帮我读取 package.json"));
  assert.ok(renderedAll.includes("read"));
  assert.ok(renderedAll.includes("package.json"));
  assert.ok(renderedAll.includes("0.1.0"));
});
