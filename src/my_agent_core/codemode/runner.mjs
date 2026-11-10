import readline from 'node:readline';
import vm from 'node:vm';
import { performance } from 'node:perf_hooks';

// Deep freeze host primordials to prevent prototype pollution
Object.freeze(Object.prototype);
Object.freeze(Array.prototype);
Object.freeze(Function.prototype);
Object.freeze(Promise.prototype);

class ExitSignal extends Error {
  constructor() {
    super('ExitSignal');
    this.name = 'ExitSignal';
  }
}

function formatText(val) {
  if (typeof val === 'string') return val;
  try {
    const str = JSON.stringify(val);
    return str !== undefined ? str : String(val);
  } catch {
    return String(val);
  }
}

function formatConsoleArg(arg) {
  if (typeof arg === 'string') return arg;
  try {
    const str = JSON.stringify(arg);
    return str !== undefined ? str : String(arg);
  } catch {
    return String(arg);
  }
}

let activeExecution = null;

const rl = readline.createInterface({
  input: process.stdin,
  terminal: false,
});

rl.on('line', async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;

  let msg;
  try {
    msg = JSON.parse(trimmed);
  } catch {
    return;
  }

  if (msg.action === 'execute') {
    if (activeExecution) return;
    await handleExecute(msg);
  } else if (msg.action === 'tool_result') {
    if (activeExecution) {
      activeExecution.handleToolResult(msg);
    }
  }
});

rl.on('close', () => {
  if (!activeExecution || !activeExecution.completedSent) {
    process.exit(0);
  }
});

process.on('unhandledRejection', (reason) => {
  if (activeExecution && !activeExecution.completedSent) {
    const errMsg = reason instanceof Error ? reason.message : String(reason);
    activeExecution.completeWithError(errMsg);
  }
});

process.on('uncaughtException', (err) => {
  if (activeExecution && !activeExecution.completedSent) {
    activeExecution.completeWithError(err?.message || String(err));
  }
});

async function handleExecute(msg) {
  const startTime = performance.now();
  let callSeq = 0;
  let hasExited = false;
  let completedSent = false;
  const pendingToolCalls = new Map();

  const text_items = [];
  const console_lines = [];
  const storeData = Object.assign({}, msg.store || {});
  const storeWrites = {};

  function getWallTime() {
    return parseFloat(((performance.now() - startTime) / 1000).toFixed(4));
  }

  function sendCompleted(payload) {
    if (completedSent) return;
    completedSent = true;
    hasExited = true;

    for (const { reject } of pendingToolCalls.values()) {
      reject(new Error('Runner terminated'));
    }
    pendingToolCalls.clear();

    const output = JSON.stringify(payload) + '\n';
    process.stdout.write(output, () => {
      rl.close();
      process.exit(0);
    });
  }

  const executionState = {
    get completedSent() {
      return completedSent;
    },
    handleToolResult(resMsg) {
      const pending = pendingToolCalls.get(resMsg.call_id);
      if (pending) {
        pendingToolCalls.delete(resMsg.call_id);
        if (resMsg.ok) {
          pending.resolve(resMsg.result);
        } else {
          const errMsg = resMsg.error || (typeof resMsg.result === 'string' ? resMsg.result : 'Tool call failed');
          pending.reject(new Error(errMsg));
        }
      }
    },
    completeWithError(errorMessage) {
      sendCompleted({
        action: 'completed',
        ok: false,
        wall_time: getWallTime(),
        text_items,
        console_lines,
        store_writes: {},
        error: errorMessage,
      });
    },
  };

  activeExecution = executionState;

  const context = vm.createContext({});

  context.__bridge = {
    text(val) {
      if (hasExited) return;
      text_items.push(formatText(val));
    },
    log(...args) {
      if (hasExited) return;
      console_lines.push(args.map(formatConsoleArg).join(' '));
    },
    store(k, v) {
      if (hasExited) return;
      storeData[k] = v;
      storeWrites[k] = v;
    },
    load(k) {
      return storeData[k];
    },
    exit() {
      hasExited = true;
      throw new ExitSignal();
    },
    callTool(name, args) {
      if (hasExited) {
        return Promise.reject(new Error('Script has already exited'));
      }
      const call_id = `call_${++callSeq}`;
      return new Promise((resolve, reject) => {
        pendingToolCalls.set(call_id, { resolve, reject });
        const payload = JSON.stringify({
          action: 'tool_call',
          call_id,
          name,
          args: args || {},
        }) + '\n';
        process.stdout.write(payload);
      });
    },
  };

  vm.runInContext(
    `
    const _bridge = __bridge;
    delete globalThis.__bridge;

    globalThis.text = function(val) { _bridge.text(val); };
    globalThis.console = {
      log: function(...args) { _bridge.log(...args); },
      info: function(...args) { _bridge.log(...args); },
      warn: function(...args) { _bridge.log(...args); },
      error: function(...args) { _bridge.log(...args); }
    };
    globalThis.store = function(k, v) { _bridge.store(k, v); };
    globalThis.load = function(k) { return _bridge.load(k); };
    globalThis.exit = function() { _bridge.exit(); };
    globalThis.tools = new Proxy({}, {
      get(target, prop) {
        if (typeof prop !== 'string' || prop === 'then') return undefined;
        return function(args) {
          return _bridge.callTool(prop, args);
        };
      },
      has(target, prop) {
        return typeof prop === 'string' && prop !== 'then';
      }
    });

    Object.freeze(Object.prototype);
    Object.freeze(Array.prototype);
    Object.freeze(Function.prototype);
    Object.freeze(Promise.prototype);
  `,
    context,
  );

  const userCode = msg.code || '';
  const wrappedCode = `(async () => {\n${userCode}\n})()`;

  try {
    const result = await vm.runInContext(wrappedCode, context);
    if (result !== undefined && !hasExited) {
      text_items.push(formatText(result));
    }
    sendCompleted({
      action: 'completed',
      ok: true,
      wall_time: getWallTime(),
      text_items,
      console_lines,
      store_writes: storeWrites,
      error: null,
    });
  } catch (err) {
    if (err instanceof ExitSignal || (err && err.name === 'ExitSignal') || hasExited) {
      sendCompleted({
        action: 'completed',
        ok: true,
        wall_time: getWallTime(),
        text_items,
        console_lines,
        store_writes: storeWrites,
        error: null,
      });
    } else {
      sendCompleted({
        action: 'completed',
        ok: false,
        wall_time: getWallTime(),
        text_items,
        console_lines,
        store_writes: {},
        error: err?.message || String(err),
      });
    }
  }
}
