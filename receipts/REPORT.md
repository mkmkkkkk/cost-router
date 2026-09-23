models=4 price_fields_known=44/48 handworked_examples=5 tests=33

合成三尝试轨迹（含失败和重试），USD：Sol 0.0606 | Luna 0.00303 | Opus 0.1176 | Opus Fast 0.2352。

策略示例：

```text
failed-attempt [extract] 保留 gpt-6-sol；Luna 仅作成本情景，每轮节省 0.01919
retry [extract] 保留 gpt-6-sol；Luna 仅作成本情景，每轮节省 0.01919
final [review] 保留 gpt-6-sol；Luna 仅作成本情景，每轮节省 0.01919
baseline=0.0606 routed=0.0606 savings_usd=0 slo=unknown latency_seconds=unknown
```

unknown：Sonnet 5.5 正式价；Sol/Luna 独立 1h 缓存写价；真实样本工具费、原模型 Astra 价格（范围外）、质量与时延证据、失败/重试标签；聚合 exec 用量的逐请求上下文边界。缺失的 reasoning 拆分不影响已知 inclusive output 总费用。

选择本机日志，因为 Nerve 预留样本起初为 0 字节；收尾时发现 23 条舰队汇总记录已到达，已优先补跑，保存字节副本与 SHA-256；原始 Nerve 文件保持原样、不提交。提取 25 条真实每请求 usage，不复制正文。选择固定 token/cache/retry 的跨模型情景，因为真实换模型的 token 用量、缓存命中与质量证据缺失。SLO 按整个串行任务计，避免把每轮达标误认为全任务达标。

红→绿：初始测试因核心模块尚未实现报 ImportError（tests-red.txt）；随后新增边界验收定位逐轮时限未应用（tests-boundary-red.txt，32 tests / 1 failure）；实现逐轮时限与质量下限后，新增舰队实样验收后，tests-green.txt 为 33 tests / OK。五组手算数字均断言，逐项验算包含缓存读写、reasoning、失败重试、Fast 双倍、长上下文和 1h 写入。

独立收据：tests/verify_receipts.py 不导入生产计算器，直接从原样本与独立费率重算，核对 790 个费用项，并读回核心交付文件记录 SHA-256。原始 CLI 文本/JSON、真实样本 repricing、路由输出以及独立复算均在本目录。

真实 25 请求已知 token 小计：Sol 0.8157508；Luna 0.04078754；Opus 1.2440968；Fast 2.4881936。完整总额全部 unknown（工具费缺失），没有把小计包装成结算账单。

blocked：真实样本的完整费用和经质量验证的模型降级结论，缺工具费与评测证据；仍交付可运行的导入、算账、规则路由与复算能力。Sonnet 5.5 未取得正式价格，不填猜测值。

范围外观察：无额外项目问题调查。未改其他项目、content 队列、网络配置或 live 服务；无浏览器操作，无外发，无 push，无后台服务。

舰队样本实跑：23 聚合记录，Sol/Luna 因逐请求上下文档位缺失，总额 unknown（known=0 仅表示没有可确定金额，不表示免费）；Opus known=44.8465624，Fast known=89.6931248，工具费缺失使完整总额 unknown。缺原模型，路由 diff 也为 unknown。见 fleet-bill.json / fleet-route.json。

收尾修正：CSV CRLF 被 git diff --check 标记，已改 LF；未绕过检查或 hooks。
