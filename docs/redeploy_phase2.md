# 交接:在新服务器上续跑 demo 阶段 2(cron 部署)

> 写给服务器上的 Claude Code。由操作者 Mac 上的 Claude Code 会话于 2026-10-11 编写。
> 你没有那次会话的上下文,这份文档就是全部上下文。先通读,再动手。

## 背景

- 旧服务器约在 2026-09-28 重装,IP 改为 新 IP(也就是本机)。
  磁盘被清空:项目、Hermes 定时任务、网格状态、订单账本全部丢失。
- 交易机器人(`scripts/lesson_28_demo_grid_loop.py`,BTC/ETH/SOL 三个网格,OKX **模拟盘**)
  最后一笔成交是 **2026-09-27 08:02 UTC**,此后再未运行。
- **操作者的决定:续跑阶段 2,不要开新网格;调度用系统 cron**(Hermes 不再装)。
- 交易所才是记录系统:成交历史都在 OKX 上,服务器只是一个可以重建的缓存。

## Mac 端会话已完成的部分

- 仓库已同步到 `/root/okx_quant_lab`,含 `.git` 历史。没有远端,提交留在本地即可。
- demo 凭证已放到 `/root/.config/okx/demo.env`(权限 600)。**不要打印它的内容。**
  私有 API 模块写死了 `x-simulated-trading: 1` 请求头,不存在实盘路径。
- 服务器上测试全绿,只读连通性检查已通过。

## 绝对不能做的事

1. **状态文件写好之前,不要以 `--confirm` 运行 lesson_28,也不要装 cron。** 发现
   `data/demo/{inst}_15m_demo_grid_state.json` 不存在时,循环会按现价**自动部署一张新网格**。
   那就成了阶段 3,约 33 USDT 的旧持仓也会被晾在网格外面。
2. **不要把历史 K 线当作实时订单重放。** 重建期间所有"下单"都只能落到假执行器上。
3. 不要手动下单,也不要撤销交易所上的任何东西。
4. 不要不带 `--confirm` 地"试跑"一次 lesson_28。它照样会推进 `last_timestamp_ms`,
   被 BLOCKED 的那根 K 线就再也不会被处理了。

## 阶段 2 的精确参数

| 项 | 值 |
|---|---|
| 部署 K 线 | 2026-09-06 14:00 UTC(15m),`deploy_timestamp_ms = 1788703200000` |
| 配置 | `scripts/lesson_28_demo_grid_loop.py` 里的 `market_config(inst)`:±15%、20 格、每市场 100 USDT、熔断 3%/天 |
| 锚定价(reference_price) | BTC 79757.4、ETH 2488.27、SOL 106.41(即 14:00 那根 K 线的收盘价) |
| 自检 | `new_demo_grid_state(cfg, ref)` 的 levels[0]/levels[-1] 必须正好是 BTC 67793.7900/91721.0100、ETH 2115.0295/2861.5105、SOL 90.4485/122.3715 |
| 部署时的初始字段 | `last_timestamp_ms = deploy_timestamp_ms = 1788703200000`(从下一根 K 线开始处理) |

## 订单 ID 能精确反推

内部 ID 由 `src/okx_quant_lab/demo_grid.py` 中的 `_buy_request` 和 `_sell_request` 生成:

```
demogrid:{inst_id}:{candle.timestamp_ms}:BUY:L{slot}
demogrid:{inst_id}:{candle.timestamp_ms}:SELL:L{slot}     # slot = 0..19,卖单也用槽位号
```

交易所上的 `clOrdId` 是 `sha256(内部ID).hexdigest()[:32]`(见 `demo_execution._exchange_client_order_id`;
阶段 2 晚于 2026-08-14 的 MD5→SHA256 切换,所以全部是 SHA256)。枚举阶段 2 窗口内
每根 15m K 线 × {BUY, SELL} × 20 个槽位,每个市场约 15 万次哈希,能把每笔成交映射回具体的 K 线和格子。

## 重建步骤

建议写成可复用脚本 `scripts/rebuild_grid_state.py` 并提交,这种事故以后可能还会发生。

1. **补齐 K 线**:用 `candle_store.refresh_candles(data/candles/{inst}_15m_demo.csv, inst, bar="15m",
   target_count=足以覆盖部署日至今, retention=12000, repair_gaps=True)`。之后 `candle_gaps()` 必须为空。
   部署日到现在大约 3,400 根 15m K 线。
2. **拉取成交**:`GET /api/v5/trade/fills-history?instType=SPOT&instId={inst}&limit=100`,
   用 `after=<最后一条的 billId>` 向更早的方向翻页,直到早于部署时间。用
   `okx_demo_private.private_request`(GET 有重试)。一笔订单可能拆成多笔成交,
   **按 clOrdId 聚合**:数量求和,均价按成交量加权,fee 求和(OKX 的手续费是负数),feeCcy 照抄。
3. **映射**:每个聚合后的 clOrdId 都必须能映射到一个内部 ID。
   **有任何一个映射不上就停下来报告**,因为那意味着有手动交易或者别的问题。
4. **重放(部署 → 停机)**:从 `new_demo_grid_state(cfg, ref)` 出发,填好部署字段,
   用 `demo_grid.advance_demo_grid(candles, state, cfg, executor, spec, confirmed=True)`
   处理部署之后、**2026-09-28 01:15 UTC 及以前**的 K 线(新机器 09-28 01:27 UTC 启动)。
   `spec` 用 `okx_public.fetch_instrument_spec(inst)`。executor 用假执行器,需要实现 `submit(request, confirmed)`:
   - 交易所上有这个 clOrdId:返回 `status="FILLED"` 的 `DemoOrderRecord`,`fill_price`、`fill_quantity`、
     `fee`、`fee_currency` 用聚合后的真实数值。如果成交名义金额明显小于请求
     (买单低于 quote 的 95%,卖单低于 base 的 95%),说明是部分成交,live 当时会记为 `PARTIAL`,
     不记账。此时返回 `PARTIAL` 并**报告**。
   - 交易所上没有:返回非 FILLED 的记录(比如 `CANCELED`)。live 当时这笔单是被撤、出错或被拦,状态同样不会变。
   - 停机时刻不必精确:机器人死后多重放的 K 线在交易所上都没有成交,效果等同于下一步的"只推进、不交易"。
5. **一致性检查**(任何一项不过都停下报告):
   - 映射上的交易所订单数必须等于重放产生的 FILLED 记录数,每笔恰好被消费一次。
   - 重建账面的 `sum(holdings)` 应接近交易所净持仓。Mac 端 2026-10-11 从成交历史算出的值是:
     BTC +0.000175、ETH +0.007337、SOL +0.000014。重放卖出时会丢弃碎股,所以允许有碎股级别的差。
   - 阶段 2 盈亏(现金加持仓按现价估值,减 300)应约为 **+3.60 USDT**。这是按 2026-10-11 的价格
     BTC 83128、ETH 2507、SOL 109.74 算的,价格变了这个数也会跟着变。
6. **快进停机缺口(不交易)**:从停机继续推进到最新一根已确认的 K 线,用一个对所有请求都返回
   `BLOCKED` 的执行器。这样只更新重新武装(re-arm)、日内熔断基线和 `last_timestamp_ms`,
   不改变 holdings 和 cash。**这些 BLOCKED 记录不写入账本。**
7. **预演第一个 live 周期**:按最新收盘价算出哪些格子会卖(持仓且 close ≥ levels[i+1]),
   哪些会买(已武装、空仓、close ≤ levels[i]、cash ≥ 5)。把清单报告出来。
   缺口期间价格动了,第一个周期可能会有几笔"追赶"订单,这是预期行为,每笔 ≤ 5 USDT。
8. **写入文件**(原子写,用项目自带的函数):
   - `demo_grid.save_demo_grid_state(data/demo/{inst}_15m_demo_grid_state.json, state)`,
     `deploy_timestamp_ms` 必须是 1788703200000。
   - `demo_execution.save_demo_order_ledger(data/orders/demo_grid_orders_{inst}.json, records)`:
     **只写 FILLED 记录**,message 写 `"reconstructed from OKX fills-history after server reinstall (2026-10-11)"`。
9. 写完运行 `python3 scripts/demo_phase_report.py` 和 `python3 scripts/daily_summary.py`(都只读)。
   前者的阶段 2 盈亏应与第 5 步一致,也不应出现"FILLED records matched"告警。

## cron 部署

服务器时区是 Asia/Shanghai,cron 按本地时间解释。分钟字段与旧系统相同;日报原来是本地 20:00。

```cron
SHELL=/bin/bash
2,17,32,47 * * * * cd /root/okx_quant_lab && { date -u +"== \%F \%T UTC"; flock -n /tmp/okx_grid.lock /usr/bin/python3 scripts/lesson_28_demo_grid_loop.py --confirm --watchdog; } >> logs/grid.log 2>&1
5 * * * *          cd /root/okx_quant_lab && { date -u +"== \%F \%T UTC"; flock -n /tmp/okx_hourly.lock /usr/bin/python3 scripts/hourly_update.py --watchdog; } >> logs/hourly.log 2>&1
0 20 * * *         cd /root/okx_quant_lab && { date -u +"== \%F \%T UTC"; /usr/bin/python3 scripts/daily_summary.py; } >> logs/daily.log 2>&1
```

- 先 `mkdir -p /root/okx_quant_lab/logs`,并确认 `systemctl is-active cron` 为 active。
- 加一份 `/etc/logrotate.d/okx_quant_lab`:weekly、rotate 8、compress、missingok、notifempty、copytruncate。
- 装好之后盯住下一个网格周期(本地时间 :02/:17/:32/:47),检查 `logs/grid.log`、状态文件的修改时间,以及账本有没有新增记录。
- **Telegram 通知目前没有。** 原来是 Hermes 负责投递的。不要自己发明一个通知通道,把这件事作为待办报告给操作者。
- 纸面策略(hourly_update)的状态也丢了,第一次运行会从当前 K 线重新起步。只是纸面,没有资金影响,在报告里说明即可。

## 完成后

- 把重建脚本和 cron/logrotate 配置副本(比如 `deploy/` 目录)提交到本地仓库,提交信息写清原因。
- 报告给操作者:映射结果(订单数、有无映射不上的)、重建账面与交易所的对账、
  第一个 live 周期实际做了什么、cron 是否已在跑、还有哪些待办(Telegram)。
