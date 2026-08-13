'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = 'D:/Program Files/xuangu';
const TAG_DIR = path.join(ROOT, 'Temp/Industry Classification_Tag');
const INPUT = path.join(TAG_DIR, 'qwen_tag_review_input.json');
const OUTPUT = path.join(TAG_DIR, 'qwen_tag_review_output.json');
const RULES = path.join(TAG_DIR, 'tag_rules.json');

const apiKey = process.env.CRECGZ_API_KEY || '';
const apiUrl = process.env.CRECGZ_API_URL || 'https://ai-api.crecgz.cn/v1/chat/completions';
const model = process.env.CRECGZ_MODEL || 'Qwen3-Instruct';

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

async function main() {
  if (!apiKey) throw new Error('CRECGZ_API_KEY 未配置，无法调用 Qwen3');
  const input = readJson(INPUT);
  const rules = readJson(RULES);
  const canonical = Object.keys(rules.canonical_groups || {});
  const system = '你是A股行业/题材标签标准化助手。你只负责把原始标签归到标准标签、建议新增标准标签或标记噪声；不得给股票打分，不得编造事实。输出严格JSON。';
  const user = `现有标准标签：${canonical.join('、')}\n\n待审原始标签如下：\n${JSON.stringify(input.items, null, 2)}\n\n输出JSON格式：{"items":[{"raw_tag":"原始","action":"map|new|block","canonical":"标准标签或建议新增标签","reason":"简短原因"}]}。如果是交易状态、地区泛概念、指数、机构持仓、融资融券、公司名、新闻废词，action=block。`;
  const payload = JSON.stringify({
    model,
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    response_format: { type: 'json_object' },
    temperature: 0,
    max_tokens: 6000,
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
  if (response.status !== 200) throw new Error(`Qwen3 HTTP ${response.status}`);
  const data = await response.json();
  const parsed = parseJson(data?.choices?.[0]?.message?.content);
  if (!parsed || !Array.isArray(parsed.items)) throw new Error('Qwen3 未返回可解析 items');
  const output = {
    updated_at: new Date().toISOString(),
    model,
    input_count: input.items.length,
    output_count: parsed.items.length,
    items: parsed.items,
  };
  fs.writeFileSync(OUTPUT, JSON.stringify(output, null, 2), 'utf-8');
  console.log(JSON.stringify({
    model,
    input_count: output.input_count,
    output_count: output.output_count,
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
