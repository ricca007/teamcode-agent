import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const storage = new Map();
globalThis.window = { localStorage: {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: (key) => storage.delete(key),
}, location: { protocol: "http:", host: "localhost" } };

function moduleUrl(source) {
  const { outputText } = ts.transpileModule(source.replaceAll("import.meta.env", "{}"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  });
  return `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`;
}

// i18n 字典是纯数据模块，测试里内联成 data URL，供 client/store/format 解析。
const dictUrl = moduleUrl(
  await readFile(new URL("../src/i18n/dict.ts", import.meta.url), "utf8"),
);

function withDict(source) {
  return source.replaceAll('"../i18n/dict"', JSON.stringify(dictUrl));
}

test("Markdown download uses the same authentication as the JSON API", async () => {
  const source = await readFile(new URL("../src/api/client.ts", import.meta.url), "utf8");
  const client = await import(moduleUrl(withDict(source)));
  client.setAuthToken("tc_test_token");
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.match(url, /interfaces\?format=markdown&lang=zh$/);
    assert.equal(init.headers.Authorization, "Bearer tc_test_token");
    return new Response("# Current interfaces", { headers: { "Content-Type": "text/markdown" } });
  };
  try {
    assert.equal(await client.getInterfaceMarkdown("p_test"), "# Current interfaces");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

async function storeWithPendingRequests() {
  const pending = [];
  const pendingInterfaces = [];
  globalThis.__tcPending = pending;
  globalThis.__tcPendingInterfaces = pendingInterfaces;
  const clientUrl = moduleUrl(`
    export const RECENT_TASK_LIMIT = 6;
    export const loadLiveBundle = () => new Promise(resolve => globalThis.__tcPending.push(resolve));
    export const getInterfaces = () => new Promise(resolve => globalThis.__tcPendingInterfaces.push(resolve));
    export const loadTaskDetail = (taskId) => Promise.resolve({
      taskId, session: null, logs: [], changes: [], warnings: [],
    });
  `);
  let source = await readFile(new URL("../src/store/useAppStore.ts", import.meta.url), "utf8");
  source = source.replace('"zustand"', JSON.stringify(import.meta.resolve("zustand")))
    .replace('"../api/client"', JSON.stringify(clientUrl));
  const { useAppStore } = await import(
    moduleUrl(withDict(source) + `\n// unique ${Math.random()}`)
  );
  return { store: useAppStore, pending, pendingInterfaces };
}

test("switching projects discards an earlier project's pending load", async () => {
  const { store, pending } = await storeWithPendingRequests();
  const loading = store.getState().load();
  store.getState().selectProject({ id: "p_new", name: "New", role: "member" });
  pending.shift()({ tasks: [], sessions: [], logs: [], changes: [], warnings: [],
    interfaces: [{ interface_id: "old_interface" }] });
  await loading;
  assert.equal(store.getState().projectId, "p_new");
  assert.deepEqual(store.getState().interfaces, []);
  assert.equal(store.getState().loading, true);
});

test("switching projects discards an earlier interface.updated response", async () => {
  const { store, pendingInterfaces } = await storeWithPendingRequests();
  store.getState().handleEvent({ type: "interface.updated", project_id: store.getState().projectId });
  store.getState().setProjectId("p_new");
  pendingInterfaces.shift()([{ interface_id: "old_interface" }]);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(store.getState().interfaces, []);
});

test("leaders see newly planned tasks and reassigned members lose the old task", async () => {
  const { store } = await storeWithPendingRequests();
  store.getState().setAuth("leader", "Leader", "leader");
  const task = { task_id: "t1", owner_id: "member1", status: "planned" };
  store.getState().handleEvent({ type: "task.updated", project_id: store.getState().projectId,
    payload: task });
  assert.equal(store.getState().tasks.length, 1);
  store.getState().setAuth("member", "Member", "member1");
  store.getState().handleEvent({ type: "task.updated", project_id: store.getState().projectId,
    payload: { ...task, owner_id: "member2" } });
  assert.deepEqual(store.getState().tasks, []);
});

test("a task without a session is not reported as a failed request", async () => {
  const source = await readFile(new URL("../src/api/client.ts", import.meta.url), "utf8");
  const client = await import(moduleUrl(withDict(source)));
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (url.endsWith("/status")) {
      return new Response(
        JSON.stringify({ code: "session_not_found", message: "任务还没有运行记录" }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.endsWith("/logs")) {
      return new Response(JSON.stringify({ logs: [] }), { status: 200 });
    }
    return new Response(JSON.stringify({ changes: [] }), { status: 200 });
  };
  try {
    const detail = await client.loadTaskDetail("task_planned");
    assert.deepEqual(detail.warnings, []);
    assert.equal(detail.session, null);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("frontend signature preserves Python argument separators", async () => {
  const source = await readFile(new URL("../src/lib/format.ts", import.meta.url), "utf8");
  const { signatureOf } = await import(moduleUrl(withDict(source)));
  assert.equal(signatureOf({ name: "lookup", kind: "function", returns: "str", params: [
    { name: "key", annotation: "str", default: null, kind: "positional_only" },
    { name: "strict", annotation: "bool", default: "True", kind: "keyword_only" },
  ] }), "def lookup(key: str, /, *, strict: bool = True) -> str");
});
