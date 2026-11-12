import type { Change, Interface, Log, Member, Plan, Task, TestResult } from "./types";
export const members: Member[] = [
  { user_id: "u_a", name: "A · 规划负责人", role: "leader" },
  { user_id: "u_b", name: "B · 运行时负责人", role: "member" },
  { user_id: "u_c", name: "C · 接口与前端", role: "member" },
];
export const tasks: Task[] = ["用户管理", "商品管理", "订单管理"].map((name, i) => ({
  task_id: `t_${i}`, title: name, description: `完成${name}模块，提供接口与测试。`, owner_id: members[i].user_id,
  status: i === 0 ? "completed" : "planned", allowed_paths: [`shop/${i}/`], depends_on: i === 2 ? ["t_0", "t_1"] : [],
  acceptance_criteria: ["提供公开接口", "通过项目测试"],
}));
export const interfaces: Interface[] = ["get_user", "list_products", "create_order"].map((name, i) => ({
  interface_id: `i_${i}`, name, kind: "function", module: ["users", "products", "orders"][i],
  file_path: ["users.py", "products.py", "orders.py"][i], version: 2, returns: "dict",
  docstring: "这是离线展示样例；真实模式从 Python AST 自动提取。", is_async: false, commit_hash: null,
  dependencies: i === 2 ? ["users.get_user", "products.list_products"] : [],
  params: [{ name: "id", annotation: "int", default: null }],
}));
export const plan: Plan = { version: 1, plan: { tasks }, diff: null };
export const logs: Log[] = [{ level: "info", message: "[离线样例] 已准备独立工作区" },
  { level: "info", message: "[离线样例] 任务完成；这里没有启动真实 Coding Agent" }];
export const changes: Change[] = [{ files: ["shop/users.py"], diff: "+def get_user(id: int) -> dict:\n+    return {}" }];
export const tests: TestResult = { status: "passed", output: "[离线模拟结果，非实际执行]\n3 passed" };
