# 输入 schema 与计费口径

JSONL 每行一个对象；CSV 使用相同列名，UTF-8，字段中的 JSON 对象按 CSV 转义。样例是 `samples/synthetic.jsonl` 和同内容的 `.csv`。未知数用 null、空单元格或字符串 `unknown`；缺失字段**不等于 0**。

| 字段 | 语义 |
| --- | --- |
| id | 可复核的尝试标识；不按此字段合并重试 |
| model | 快照模型 ID，如 `gpt-6-sol`、`claude-opus-5-5:fast`；未知模型保留，不猜别名 |
| mode | 可选 standard（通用记录默认）、fast、unknown；Fast 拼成模型 ID 的 `:fast` 后缀 |
| input_tokens | 默认 inclusive：含普通输入、缓存读、缓存写的总输入 |
| cached_input_tokens | 缓存命中数量；必须显式 0 才表示没有 |
| cache_write_input_tokens | 写入缓存数量；不能再按普通输入收费 |
| input_semantics | inclusive（默认）或 exclusive；后者适用于厂商原始非缓存 input，导入后加回读写，统一为 inclusive |
| cache_write_ttl | 5m、1h、provider_default、unknown；Opus 有写入时必须明确 5m/1h，否则写入费 unknown；OpenAI 默认写入档不据此推断独立 1h 价 |
| output_tokens | **包含 reasoning** 的总输出，不是仅可见文本 |
| reasoning_output_tokens | output 的子集；未知时整笔 output 按输出费率计一次，reasoning 标记 included_in_output |
| retry | true/false/unknown，只是标签，不额外乘重试系数 |
| status | completed/failed/unknown 等标签；无论状态均计入已发生的用量 |
| granularity | request（通用默认）或 aggregate；聚合记录不猜长上下文档位 |
| tool_cost_usd | 每尝试工具费总额，或 `{模型ID:金额}`；没有额外工具费时**显式 0**，缺失为 unknown。跨模型共享数值表示调用方明确声明其相同 |
| kind | 如 extract、review、repair；不据标签主观推断模型能力 |
| latency_limit_seconds | 可选逐轮时限；全任务时限仍由 CLI SLO 给出 |
| quality_min_ratio | 可选逐轮质量下限，baseline=1；不会放宽全局 baseline 下限 |
| evidence | `{模型ID:{quality_vs_baseline:1,latency_seconds:3,source:"eval-id",kind:"extract"}}`；时延须涵盖该次尝试的排队、工具及回退等待等开销 |

所有 token 是有限非负整数；费用/时延/质量比是有限非负数。读+写不能超过 inclusive input，reasoning 不能超过 output。未知计费项使总额为 unknown，`known_subtotal_usd` 只加已知项。工具费是费用库存接口；未提供工具数量/计费周期/金额时不从 token 猜工具费。

Codex `exec --json`：读取 `turn.completed` 与 `turn.failed` 的 `usage`，原样接收五个 token 字段；无 usage 的失败也留下未知尝试。工具事件不是额外 token 行。缺少模型或 cache-write 字段不会自动补 0。

本机 native sessions：优先读取 `token_usage_record.payload.usage`（逐请求），使用最近 `turn_context` 模型；相同 session/response ID 的相同 usage 去重，冲突时报错。忽略同文件中作为镜像的累计 `token_count`。只有无 request records 时才使用 `event_msg.token_count.info.total_token_usage` 的增量；相同总量不重复计，累计倒退报错，不能偷偷把重置当作零。该回退导入结果是 aggregate。不要把来自多个来源的重叠数据拼成一个文件。

本期口径为第一方全球 API token 情景。不同地区附加费、税、合同折扣、订阅积分、Batch 及非本期模型模式不在快照范围，不能用这个结果宣称这些渠道的完整结算费用。超过已知上下文容量的记录会标记 replay infeasible。所有跨厂商比较保持给定 token 数量、缓存命中和尝试次数，不代表真实重新运行会得到相同用量。
