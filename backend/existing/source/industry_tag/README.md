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
