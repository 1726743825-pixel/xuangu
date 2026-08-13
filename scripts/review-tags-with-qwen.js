'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = 'D:/Program Files/xuangu';
const TAG_DIR = path.join(ROOT, 'Temp/Industry Classification_Tag');
const INPUT = path.join(TAG_DIR, 'qwen_tag_review_input.json');
const OUTPUT = path.join(TAG_DIR, 'qwen_tag_review_output.json');
const DEBUG_OUTPUT = path.join(TAG_DIR, 'tag_review_model_debug.json');
const RULES = path.join(TAG_DIR, 'tag_rules.json');

const qwenApiKey = process.env.CRECGZ_API_KEY || '';
const qwenApiUrl = process.env.CRECGZ_API_URL || 'https://ai-api.crecgz.cn/v1/chat/completions';
const qwenModel = process.env.CRECGZ_MODEL || 'Qwen3-Instruct';
const deepseekApiKey = process.env.DEEPSEEK_API_KEY || '';
const deepseekApiUrl = process.env.DEEPSEEK_API_URL || 'https://api.deepseek.com/chat/completions';
const deepseekModel = process.env.DEEPSEEK_MODEL || 'deepseek-v4-flash';
const batchSize = Math.max(5, Number.parseInt(process.env.TAG_REVIEW_BATCH_SIZE || '10', 10) || 10);

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf-8'));
}

function parseJson(content) {
  const text = String(content || '').trim();
  const candidates = [text];
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fenced?.[1]) candidates.push(fenced[1].trim());
  const first = text.indexOf('{');
  const last = text.lastIndexOf('}');
  if (first >= 0 && last > first) candidates.push(text.slice(first, last + 1));
  for (const item of candidates) {
    try { return JSON.parse(item); } catch {}
  }
  return null;
}

function normaliseModelItems(parsed) {
  if (Array.isArray(parsed)) return parsed;
  if (Array.isArray(parsed?.items)) return parsed.items;
  if (Array.isArray(parsed?.results)) return parsed.results;
  if (Array.isArray(parsed?.tags)) return parsed.tags;
  return [];
}

async function callModel({ provider, apiKey, apiUrl, model, input, canonical }) {
  if (!apiKey) return null;
  const system = '你是A股行业/题材标签标准化助手。你只负责把原始标签归到标准标签、建议新增标准标签或标记噪声；不得给股票打分，不得编造事实。不要解释，不要推理过程，不要Markdown，只输出严格JSON。';
  const user = `现有标准标签：${canonical.join('、')}\n\n待审原始标签如下：\n${JSON.stringify(input.items, null, 2)}\n\n输出JSON格式：{"items":[{"raw_tag":"原始","action":"map|new|block","canonical":"标准标签或建议新增标签","reason":"简短原因"}]}。如果是交易状态、地区泛概念、指数、机构持仓、融资融券、公司名、新闻废词，action=block。`;
  const payload = JSON.stringify({
    model,
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    response_format: { type: 'json_object' },
    temperature: 0,
    max_tokens: 9000,
  });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  let response;
  try {
    response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
        'Content-Length': Buffer.byteLength(payload),
      },
      body: payload,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
  if (response.status !== 200) throw new Error(`${provider} HTTP ${response.status}`);
  const data = await response.json();
  const content = data?.choices?.[0]?.message?.content;
  const parsed = parseJson(content);
  const items = normaliseModelItems(parsed);
  if (!items.length) {
    fs.writeFileSync(DEBUG_OUTPUT, JSON.stringify({
      updated_at: new Date().toISOString(),
      provider,
      model,
      content_preview: String(content || '').slice(0, 4000),
      raw_keys: data && typeof data === 'object' ? Object.keys(data) : [],
    }, null, 2), 'utf-8');
    throw new Error(`${provider} 未返回可解析 items`);
  }
  return {
    provider,
    model,
    items,
  };
}

async function callModelBatched({ provider, apiKey, apiUrl, model, input, canonical }) {
  const allItems = [];
  async function callBatch(items) {
    const batch = { ...input, items };
    try {
      return await callModel({ provider, apiKey, apiUrl, model, input: batch, canonical });
    } catch (error) {
      if (items.length <= 5) throw error;
      const middle = Math.ceil(items.length / 2);
      const left = await callBatch(items.slice(0, middle));
      const right = await callBatch(items.slice(middle));
      return { provider, model, items: [...left.items, ...right.items] };
    }
  }
  for (let index = 0; index < input.items.length; index += batchSize) {
    const result = await callBatch(input.items.slice(index, index + batchSize));
    allItems.push(...result.items);
  }
  return { provider, model, items: allItems };
}

function validCoverage(result, input) {
  if (!result?.items?.length) return 0;
  const rawSet = new Set((input.items || []).map(item => String(item.raw_tag || '').trim()).filter(Boolean));
  const covered = result.items.filter(item => rawSet.has(String(item.raw_tag || '').trim())).length;
  return rawSet.size ? covered / rawSet.size : 0;
}

async function main() {
  const input = readJson(INPUT);
  const rules = readJson(RULES);
  const canonical = Object.keys(rules.canonical_groups || {});
  const deepseekOnly = process.argv.includes('--deepseek-only');
  let result = null;
  if (!deepseekOnly) {
    try {
      result = await callModelBatched({
        provider: 'qwen3',
        apiKey: qwenApiKey,
        apiUrl: qwenApiUrl,
        model: qwenModel,
        input,
        canonical,
      });
    } catch (error) {
      console.error(`Qwen3 复核失败，准备 DeepSeek 兜底: ${error.message || error}`);
    }
  }
  if ((!result || validCoverage(result, input) < 0.95) && deepseekApiKey) {
    const fallback = await callModelBatched({
      provider: 'deepseek',
      apiKey: deepseekApiKey,
      apiUrl: deepseekApiUrl,
      model: deepseekModel,
      input,
      canonical,
    });
    if (!result || validCoverage(fallback, input) >= validCoverage(result, input)) result = fallback;
  }
  if (!result) throw new Error('Qwen3 与 DeepSeek 均未返回可用标签复核结果');
  const output = {
    updated_at: new Date().toISOString(),
    provider: result.provider,
    model: result.model,
    input_count: input.items.length,
    output_count: result.items.length,
    coverage: validCoverage(result, input),
    items: result.items,
  };
  fs.writeFileSync(OUTPUT, JSON.stringify(output, null, 2), 'utf-8');
  console.log(JSON.stringify({
    provider: output.provider,
    model: output.model,
    input_count: output.input_count,
    output_count: output.output_count,
    coverage: output.coverage,
    map: output.items.filter(x => x.action === 'map').length,
    new: output.items.filter(x => x.action === 'new').length,
    block: output.items.filter(x => x.action === 'block').length,
    output: OUTPUT,
  }, null, 2));
}

main().catch(error => {
  console.error(error.message || error);
  process.exit(1);
});
