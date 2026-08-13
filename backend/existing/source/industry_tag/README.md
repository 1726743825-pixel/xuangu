# 行业分类与题材标签统一接口

目录：`D:\Program Files\xuangu\Temp\Industry Classification_Tag`

## 目标

不同数据源会使用不同标签，例如“AI服务器”“算力”“数据中心”都可能指向同一条交易主线。这里统一转换为标准标签，再参与消息面加分池匹配。

## 文件

- `tag_rules.json`：人工维护的标准行业/题材映射规则。
- `tag_normalizer.js`：脚本调用接口。
- `unknown_tags_queue.json`：运行时发现但未能映射的新标签队列，等待 DeepSeek/人工复核。

## 规则

1. 所有来源标签先走 `normalizeTags()`。
2. 命中 `canonical_groups` 时，统一为标准标签。
3. 命中 `blocked_tags` 时直接丢弃。
4. 未命中规则的标签不直接参与加分，写入 `unknown_tags_queue.json`。
5. 如果 DeepSeek 当天消息面定稿中出现新增方向，该方向可作为 `trustedNewTags` 临时可信标签参与匹配。
6. 后续人工或 DeepSeek 复核确认后，再把高频未知标签加入 `tag_rules.json`。

## 调用示例

```js
const tagNormalizer = require('./tag_normalizer');

const tags = tagNormalizer.normalizeTags(['AI服务器', '算力', '未分类'], {
  trustedNewTags: ['新型科技突破方向'],
  context: { source: 'qwen3-stock-tag', example: '某公司新增AI服务器业务' }
});
// => ['AI算力与服务器']
```

## 全量标签扫描与 Qwen3 复核

本目录已经执行过一次全量扫描：

- 扫描脚本：`E:\CodexOutput\xuangu\scripts\collect-industry-tags.js`
- Qwen3 复核脚本：`E:\CodexOutput\xuangu\scripts\review-tags-with-qwen.js`
- 汇总文件：`all_tags_summary.json` / `all_tags_summary.md`
- Qwen3 复核输出：`qwen_tag_review_output.json`
- Qwen3 复核总结：`qwen_tag_review_summary.md`

当前结论：Qwen3 仅可作为初筛和归类建议，所有关键结果必须由 DeepSeek 兜底或复核，不能无校验直接改规则。原因是少数结果存在 action 与 canonical 语义不一致。因此当前自动采纳规则为：

1. `action=map` 且 `canonical` 已存在于 `tag_rules.json`，自动把 raw_tag 加入对应别名。
2. `action=block` 自动加入 `blocked_tags`。
3. `action=new` 或 canonical 不明确的结果进入 `qwen_tag_review_pending.json`，等待 DeepSeek 或人工复核。


补充：Qwen3 能力不稳定，所有 Qwen3 处理信息的任务必须有 DeepSeek 兜底。标签复核脚本支持 `--deepseek-only`，默认分批处理（TAG_REVIEW_BATCH_SIZE，默认10），避免 DeepSeek 长 JSON 被截断；如果 Qwen3 失败、覆盖不足或输出格式异常，会切换 DeepSeek。
