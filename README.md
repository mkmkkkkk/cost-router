# cost-router — 任务成本路由验算器

> 在线试算: https://cost.mkyang.ai · 粘贴你的 codex / 通用 JSONL/CSV 用量日志, 当场看 GPT-6 Sol / Luna / Opus 5.5 / Opus Fast 四档逐项账单与路由建议。价格快照 2026-09-24, 每字段带来源。

为什么你的账单和你想的不一样：输入不全是普通输入；缓存读、缓存写有自己的费率，reasoning 通常已包含在 output 中，不能再加一次。失败尝试也可能消耗 token，重试不会抵消前一次账单。长上下文可能使**整次请求**进入更高费率，Fast 也不是免费提速。缺少用量、工具费或请求边界时，一个漂亮的总额反而可能是错的。本工具保留逐项收据；不完整的总额写 `unknown`，另列已知小计。

纯 Python 3.10+ / 标准库，无外部服务、API 调用或安装依赖。所有金额为 Decimal 美元。

```sh
cd ~/Documents/Workspace/cost-router
export PATH="$PWD:$PATH"
cost-router bill samples/synthetic.jsonl --prices prices/2026-09-24.json --models all
cost-router bill samples/fleet-import.snapshot.jsonl --models all --json
cost-router bill samples/local-usage.jsonl --models all --json
cost-router bill samples/synthetic.csv --models original
cost-router route samples/synthetic.jsonl --slo 'latency<=30s,quality>=baseline'
python3 -m unittest discover -s tests -v
python3 tests/verify_receipts.py
```

也可直接 `./cost-router …` 或 `python3 -m cost_router …`。`--json` 输出逐轮用量、费率、费用、汇总和 unknown 清单；文本模式输出同样的账单费用。空输入、坏行、不合法数字返回退出码 2；有 unknown 的有效报告仍可输出，调用方应检查 `total_usd`/`slo_status`。

价格快照是 **2026-09-24（Asia/Shanghai）**，抓取时间使用 UTC（因此日期可能为 09-23）。只计第一方 API 全球标准价及 Opus Fast，不是 Codex/Claude 订阅实际扣款。`prices/2026-09-24.json` 每个字段含来源 URL、抓取时间；OpenRouter 仅交叉核对。`models=4` 表示 3 个模型、4 个模型/模式组合。`price_fields_known=44/48` 分母为 4 × 2 上下文档位 × 6 token 价格字段，包含 output 内 reasoning 的同价标注，不包含工具费元数据；四个 unknown 是 Sol/Luna 两档的单独 1h 写入费率。不存在正式价的 Sonnet 5.5 放入 `unavailable_models`，不混用 Sonnet 5 的价格。

| 模型/模式 | input | cache read | cache write 默认/5m | cache write 1h | output（含 reasoning） |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-6 Sol | 2 | 0.20 | 2.50 | unknown | 10 |
| GPT-6 Luna | 0.10 | 0.01 | 0.125 | unknown | 0.50 |
| Opus 5.5 | 4 | 0.20 | 5 | 8 | 20 |
| Opus 5.5 Fast | 8 | 0.40 | 10 | 16 | 40 |

表中为短上下文 USD/百万 token。Sol/Luna **输入 >272000** 时，整次请求 input/cache 费率 ×2、output ×1.5；Opus 在 1M 窗口内无长上下文加价。OpenAI 缓存写入是替代输入档位，不是输入费之外再收费。来源：[OpenAI 定价](https://developers.openai.com/api/docs/pricing)、[缓存计费](https://developers.openai.com/api/docs/guides/prompt-caching)、[Sol 模型边界](https://developers.openai.com/api/docs/models/gpt-6-sol)、[Claude 定价](https://platform.claude.com/docs/en/about-claude/pricing)、[Fast 文档](https://platform.claude.com/docs/en/build-with-claude/fast-mode)、[Opus 公告及 Sonnet 发布状态](https://www.anthropic.com/claude-opus-5-5)。逐字段记录为复核依据；将来应新增快照，不覆盖历史价格。

输入约定见 [schema](docs/schema.md)。一个通用记录就是**一次尝试**；失败和重试各占一条，不根据 `retry=true` 再乘倍数。`turn.completed`/`turn.failed` 默认是可能含多次请求的聚合用量，因此 Sol/Luna 无法确定长上下文档位；不能把多次请求的输入之和当成某一次的上下文。若生成方保证是一条请求，可明确写 `granularity=request`。

本机样本 `samples/local-usage.jsonl` 是 25 条真实每请求 token 记录，仅含模型与用量，没有任务正文。提取来源、时间与原日志哈希见 `samples/local-usage.provenance.json`。Nerve 的 fleet 文件开始为 0 字节；收尾时 23 条舰队汇总记录已到达，已优先补跑并保存只读副本 `samples/fleet-import.snapshot.jsonl` 及来源哈希。该样本没有模型、工具费或逐请求边界，Sol/Luna 金额 unknown；Opus/Fast 可算已知 token 小计 44.8465624 / 89.6931248，完整总额仍 unknown。原始 Nerve 文件保持不变。真实样本原模型为 GPT-6 Astra（本期定价范围外），原账单和路由 diff 为 unknown；工具费、失败/重试标签、质量/时延证据也缺失。真实样本 repricing 的已知 token 小计不是已结算账单。

路由规则：按轮次 `kind` 匹配调用方提供的评测证据，满足 `quality_vs_baseline>=1`（或更严格的逐轮下限）及逐轮时限，再在**整个串行任务**时限内选择总成本最低的组合。只有完整价格且证据有来源的候选才参与。缺乏完整可行证据时保留原模型，仅给出固定 token/cache/retry 轨迹的成本情景；不宣称可降级、不把宣传速度当作时延测量。评测来源不经本工具独立认证，支持状态也不是性能保证。跨模型 tokenizer、输出长度、缓存失效、重试次数可能变化，所有替代模型金额都是固定轨迹情景。

手算验收见 [5 组公式与逐项金额](docs/handworked.md)。独立复算程序不调用计算器，读取原用量和已生成账单逐项核对。红→绿测试及 CLI 原始输出保存在 [receipts](receipts/)。网页版 (粘贴/拖入日志即算, 不上传): **https://cost.mkyang.ai** (源码 `web/`, 与 CLI 同一套计算, 见 `tests/test_web_parity.py`)。
