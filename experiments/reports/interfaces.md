# 接口提取与文档维护评测

> 生成时间：2026-11-09 18:27:10
> 样例项目：`experiments/fixtures/shop_app`
> 评测方式：AST 提取结果与人工标注 `expected.json` 逐字段比对；版本与实时推送使用临时 SQLite 数据库复现。

## 实验三：实时接口发现与共享

### 提取准确率

| 指标 | 值 |
| --- | --- |
| 人工标注接口数 | 11 |
| AST 提取接口数 | 11 |
| 匹配接口数 | 11 |
| 缺失接口 | 0 |
| 多余接口 | 0 |
| 字段级准确率 | 100.00% |
| docstring 覆盖率 | 100.00% |

### 扫描性能

| 指标 | 值 |
| --- | --- |
| 全量扫描耗时（3 次均值） | 1.16 ms |
| 增量扫描耗时（无变更） | 0.32 ms |
| 增量扫描重扫文件数 | 0 |
| 增量扫描跳过文件数 | 3 |

### 变更到实时事件

| 指标 | 值 |
| --- | --- |
| 防抖窗口 | 100 ms |
| 成功收到事件的轮次 | 3 / 3 |
| 平均端到端延迟（含防抖） | 117.67 ms |

### 字段明细

| 接口 | module | kind | returns | params |
| --- | --- | --- | --- | --- |
| `orders.OrderService` | ✅ | ✅ | ✅ | ✅ |
| `orders.OrderService.create_order` | ✅ | ✅ | ✅ | ✅ |
| `products.ProductService` | ✅ | ✅ | ✅ | ✅ |
| `products.ProductService.adjust_stock` | ✅ | ✅ | ✅ | ✅ |
| `products.list_products` | ✅ | ✅ | ✅ | ✅ |
| `users.UserRepository` | ✅ | ✅ | ✅ | ✅ |
| `users.UserRepository.find` | ✅ | ✅ | ✅ | ✅ |
| `users.UserService` | ✅ | ✅ | ✅ | ✅ |
| `users.UserService.create` | ✅ | ✅ | ✅ | ✅ |
| `users.get_user` | ✅ | ✅ | ✅ | ✅ |
| `users.normalize_email` | ✅ | ✅ | ✅ | ✅ |

## 实验五：自动文档维护

| 检查项 | 结果 |
| --- | --- |
| 首次扫描注册接口数 | 11 |
| 内容未变时不升版本 | ✅ |
| 签名变化触发更新 | ✅ |
| 更新后版本号 | v2 |
| 历史快照条数 | 2 |
| 删除文件后软删除 | ✅ |
| 删除快照标记 | ✅ |
| 删除后剩余接口数 | 9 |
| Markdown 含最新签名 | ✅ |
| Markdown 含使用说明 | ✅ |

- 函数名、参数、返回类型、模块与文件路径均由 Python AST 客观提取，字段级准确率 100.00%。
- 接口内容变化时 version 自增并写入 `interface_versions` 快照；删除采用软删除，历史仍可追溯。
- Markdown 文档由同一 service 生成，CLI / REST / MCP 三个出口内容一致。

## 说明

- 增量扫描基于文件 sha256 缓存；无变更时只做哈希校验，不解析 AST。
- 语法错误文件会被跳过并记录 warning，不会中断整体扫描，也不会误删已有接口。
- 实时延迟包含 100ms 防抖窗口，实际推送通常在防抖后立即完成。
- 本报告可直接放入课程实验文档。

