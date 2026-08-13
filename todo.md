# OKX Quant Lab — 优化待办清单

> 来源：2026-08-13 全量代码审查。测试基线：`python3 -m unittest` → 115 tests, OK。
> 备注：原 P0-1（`.claude/settings.local.json` 中的明文 root 密码：需轮换密码、改用 SSH 密钥、配置项移出仓库）按约定不列入本清单，另行处理。

## 第 0 步 — 前置（先于一切代码改动执行）

- [ ] **`git init` + `.gitignore` + 基线提交**
  - 项目目前无版本控制。忽略：`data/`、`reports/`、`__pycache__/`、`.DS_Store`、`.claude/`（含凭证）、`freqtrade_lab/user_data/`（sqlite/feather）。
  - 动作：初始化后做首个提交（README + todo + src + scripts + tests + docs），此后每个清单项完成即提交（README 里已手记 5 次修复，git 历史本该承担）。
  - 排序理由：P1 大规模去重的安全网是"每步测试全绿、改坏可回退"——没有基线提交,"回退"只能靠手撤。此项必须先于所有重构（2026-08-13 复核时从 P3 提前）。

## P0 — 紧急修复

- [ ] **P0-2 `demo_execution.submit` 异常捕获过窄（审计链漏洞）**
  - 位置：`src/okx_quant_lab/demo_execution.py:92-96`，当前只捕获 `RuntimeError`；网络异常 `TimeoutError`/`URLError` 是 `OSError` 子类，会直接穿透。
  - 后果：下单途中的超时不写入账本（违背"blocked/rejected/errored 都记账"的设计承诺），且 `client_order_id` 未被占用 → 下次运行可能用同一 ID 重试 → 潜在双成交。
  - 动作：改为 `except Exception as error`（审计路径求全：`OSError` 覆盖网络异常、`ValueError` 覆盖非 JSON 响应的 `JSONDecodeError`、`KeyError`/`AttributeError` 覆盖畸形 payload——一旦请求可能已触达交易所，任何失败都必须落账占 ID）；记录 message 带异常类型名（裸 `TimeoutError()` 的 `str()` 为空串）。
  - 验证：`tests/test_demo_execution.py` 增加用例：`request_fn` 抛 `TimeoutError` / `HTTPError` / `ValueError`（非 JSON payload）→ 均返回 `ERROR` 记录，且重复提交同 ID 返回 `DUPLICATE`；并断言 ERROR 记录经 `save_demo_order_ledger` 落盘后重载仍占 ID。

> 更正记录（2026-08-13）：原 P0-3（dry_run 窗口"差一根"）经复核为**误报**——dry_run 用含最新已确认收盘价的窗口是回测约定在实盘端的正确对应，两侧成交时刻均为 open[t+1]；已改为 P3 的锁定测试项。原"retire_grid 抛 FileExistsError"与"safe_demo 丢弃已有数据"两条理由亦有误，见对应条目更正。

## P1 — 代码去重

- [ ] **提取共享工具 `utils.py`（滑点 / 回撤 / 成交数学）**
  - `_slipped_price` 逐字复制 ×7：`backtest.py:223-229`、`grid_strategy.py:218-224`、`donchian_strategy.py:145-151`、`rsi_strategy.py:143-149`、`paper.py:178-184`、`grid_paper.py:198-204`、`donchian_paper.py:144-150`
  - `_max_drawdown_pct` 复制 ×5：`backtest.py:211-220`、`grid_strategy.py:208-215`、`donchian_strategy.py:135-142`、`rsi_strategy.py:133-140`、`portfolio.py:91-98`
  - 买卖成交公式（spend/fee/quantity）复制 ×5：`backtest.py:132-157`、`paper.py:107-159`、`donchian_paper.py:89-141`、`donchian_strategy.py:97-127`、`rsi_strategy.py:93-125`
  - 动作：新建 `src/okx_quant_lab/utils.py`（或 `fees.py` + `stats.py`），逐个模块替换 import，每步跑全量单测。
  - 验证：替换前后 115 tests 保持全绿；无行为变化。

- [ ] **提取状态持久化 `state_store.py`（原子写 + schema 版本）**
  - 位置：`paper.py:92-104`、`grid_paper.py:155-170`、`dry_run.py:125-133`、`demo_execution.py:214-224`、`candle_store.py:21-39` 均为非原子直写；仅 `demo_grid.py:202-224` 是原子写。
  - 动作：统一实现 `save_json_atomic(path, obj)`（tmp + `os.replace`）+ 状态文件增加 `schema_version` 字段与加载时迁移钩子（吸取 `backfill_deploy_ts.py` 一次性的教训）。
  - 验证：补测试：写入中途抛异常 → 原文件完好；旧版状态文件可迁移。

- [ ] **合并三份 walk-forward / 参数扫描骨架**
  - 位置：`walk_forward.py:44-67` / `grid_walk_forward.py:45-69` / `donchian_walk_forward.py:47-70`；其 `summarize_*` 与 `_validate_*` 三份逐字相同；`optimization.py:53-84` / `grid_optimization.py:38-79` / `donchian_optimization.py:38-65` 结构相同。
  - 动作：提取通用窗口切分/汇总/校验到共享模块，各家族只保留信号函数，以回调参数注入。
  - 验证：三个 walk-forward 测试文件全绿，输出数值不变。

- [ ] **`donchian_paper` 复用 `paper` 的成交函数而非复制**
  - 位置：`donchian_paper.py:14-15`（注释自认复制）、`donchian_paper.py:89-141` 复制了 `_paper_buy/_paper_sell/_slipped_price`。
  - 动作：改为 import `paper.py` 的成交逻辑（仅 signal 不同）。

- [ ] **`reconcile_grids` 纯函数移入 `src/okx_quant_lab/`**
  - 位置：`daily_summary.py:21-23` 把 `scripts/` 塞进 `sys.path` 再 import；`tests/test_reconcile_grids.py:17` 越过包边界。
  - 动作：纯函数移入包内，更新两处 import，删除 sys.path hack。
  - 验证：`tests/test_reconcile_grids.py` 全绿。

- ~~合并 5 份同构 Config dataclass~~ **决定不做**（2026-08-13 复核）：各家族默认值差异（如 Paper 20/50/2bps/0.5 vs Backtest 10/30/0bps/1.0）是有语义的，frozen dataclass 继承默认值顺序易碎，是清单里唯一"做了可能比不做糟"的重构项。

## P1 — 数据正确性与健壮性

- [ ] **统一蜡烛缓存刷新策略（修 stale 缓存）**
  - 现状：`lesson_08:72-80` 的 `_load_or_fetch` 只要本地行数够就永远不再刷新 → BTC/XRP/DOGE 的 `_scan.csv` 自 6 月起陈旧，依赖它们的 lesson 13/14/18/23/25 与 lesson 10 的 freshness 检查最终必然 FAIL；`lesson_19:69-84` / `lesson_20:101-116` 只在缺失时抓取。
  - 动作：在 `candle_store.py` 实现统一 `refresh_candles(path, inst_id, bar, ...)`：存在 → 增量合并（时间戳去重，已有逻辑），不足 → 补抓；替换 `hourly_update.py:165-171`、`lesson_28:115-120` 等 6 处自实现。

- [ ] **私有 API 重试 + 429 退避（区分 GET/POST，POST 必须幂等）**
  - 位置：`okx_demo_private.py:114-128` 单次请求无重试；`okx_public.py:173-183` 重试无抖动、不区分错误类型。
  - 动作：GET（查单/余额）加 3 次重试；**POST 下单不做盲重试**——超时后原单可能已在交易所成交，盲重试即双成交（与 P0-2 防的是同一风险）。POST 重试仅限携带同一 `clOrdId`（现有 md5 确定性哈希保证），遇 "clOrdId 已存在" 类拒单 → 转 `_fetch_order_details` 对账确认状态，而非当失败。公开请求按 `Retry-After` 退避、区分 429/5xx 与网络错误。

- [ ] **`retire_grid.py` 归档加时间戳（防静默覆盖历史归档）**
  - 位置：`retire_grid.py:81-82` 的 `rename` 在 POSIX（本机 darwin + Linux 服务器）上目标已存在时是**静默覆盖**——`FileExistsError` 是 Windows 行为，在此环境不适用。
  - 风险：工具重跑会悄悄毁掉上一份归档，与"退役留痕"的初衷相反。
  - 动作：归档名带时间戳/序号（如 `.json.retired.20260813`），保留全部历史归档。

- [ ] **入口脚本对缺失/损坏数据文件的兜底**
  - 位置：`lesson_25_lab_scoreboard.py:37-39`、`lesson_10_monitoring_report.py:33-36` 直接崩溃；对齐 `hourly_update.py:67-71`、`daily_summary.py:82-86` 已有的兜底模式。

## P2 — 性能

- [ ] **订单账本改用 dict 索引（真实累积成本）**
  - 位置：`demo_execution.py:192-203`、`dry_run.py:118-122` 的 `_find_by_client_order_id` 每次提交线性扫全量账本 → O(记录数)/单；`lesson_28` 每 15 分钟回放约 12000 根 K 线 × 20 slot，账本无界增长。
  - 动作：内存中维护 `dict[client_order_id, record]`，序列化时保持 list 顺序。

- [ ] **`portfolio.py` 去 O(T²·L)**
  - 位置：`portfolio.py:55-61` 对每个时间戳重建整张 leg 字典。
  - 动作：循环外每 leg 建一次 dict 再求和。

- [ ] **扫描类脚本分离信号计算与成交重放**
  - 位置：`risk.py:63-94` 对 4 个 `trade_fraction` 各跑一遍完整 `run_sma_backtest`（信号与仓位无关）；`optimization.py` 每次组合重复提取/排序 closes。
  - 动作：信号算一次，不同 allocation 只重放成交。

- [ ] **纸面循环改 O(1) 滚动窗（对齐 backtest）**
  - 位置：`paper.py:65-67`、`donchian_strategy.py:58-59`、`donchian_paper.py:60-61` 每根蜡烛重切窗口；`backtest.py:62-87` 已有滚动和示范。
  - 动作：统一改为滚动和/滚动 max-min。

- [ ] **重复排序与全量重写的清理**
  - `paper.py:54`、`donchian_paper.py:46`、`demo_grid.py:81` 对已升序输入重复 `sorted()`。
  - `hourly_update.py:165-171` 每小时全量重写增长中的 CSV → 加保留窗口裁剪（对齐 `lesson_28` 的 `CANDLE_RETENTION`）。

## P3 — 工程化

> `git init` 已提前至"第 0 步"（见文件顶部）。

- [ ] **声明 Python ≥ 3.10**
  - 代码使用 `X | None` 联合类型与内建泛型（如 `okx_public.py:92`、`backtest.py:8`）；纯 stdlib，无三方依赖。
  - 动作：加 `pyproject.toml`（`requires-python = ">=3.10"`）或在 README 声明。

- [ ] **补测试盲区**
  - 零测试：`hourly_update.py`、`daily_summary.py`、`show_ledger.py`、`retire_grid.py`、`lesson_28_demo_grid_loop.py`。
  - 极薄：`okx_public`（1 个）、`scanner`（1）、`portfolio`（2）、`risk`（2）。
  - 重点补：① 锁定三种网格触发语义差异（`grid_strategy` high/low vs `demo_grid` close-confirmed），防重构时被无意统一；② **dry-run 与 backtest 信号对齐的锁定测试**：对每个 t（`slow_window - 1 ≤ t ≤ N-2`，上界因 backtest 需 index `t+1` 存在），断言 `sma_signal(candles[:t+1])` == backtest 在 index `t+1` 的 `wants_long`。实现注意：backtest 不对外暴露逐步 `wants_long`，测试需自建小 helper 按同一约定算滚动均值（或导出决策序列）来比。两侧在**同一成交时刻**（open[t+1]）的约定一致：backtest 在 t+1 决策用 closes≤t 并成交于 open[t+1]（`backtest.py:68-86,138`），dry-run 在蜡烛 t 收盘后用 closes≤t 算信号、市价单 ≈ open[t+1] 成交（`dry_run.py:40`；`okx_public.py:73-74` 默认过滤未确认蜡烛，无偷看）。用测试锁死此对齐，防止将来被当作 off-by-one "修"坏（2026-08-13 审查曾误报此点为 bug）。

- [ ] **`safety.py` 纵深防御**
  - 位置：`safety.py:6` 的 `VALID_MODES` 含 `"live"`；目前实盘防线仅依赖 `DemoOrderExecutor` 硬编码 `mode="demo"`（`demo_execution.py:73`）。
  - 动作：gate 内对 `live` 直接拒绝，或加环境变量总开关（如 `OKX_ALLOW_LIVE=1` 才放行），不依赖调用方自觉。

- [ ] **（可选）小修**
  - `demo_execution.py:227-230` 订单 ID 哈希 MD5 → SHA256 前 32 位（消安全扫描告警）。
  - `demo_execution.py:139-146` `_fetch_order_details` 校验返回 `ordId` 与请求匹配，防止对账静默错配。
