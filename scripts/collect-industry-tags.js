'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = 'D:/Program Files/xuangu';
const TAG_DIR = path.join(ROOT, 'Temp/Industry Classification_Tag');
const tagNormalizer = require(path.join(TAG_DIR, 'tag_normalizer.js'));

function readText(file) {
  try { return fs.readFileSync(file, 'utf-8'); } catch { return ''; }
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf-8')); } catch { return null; }
}

function walk(dir, acc = []) {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, acc);
    else acc.push(full);
  }
  return acc;
}

function cleanHtml(value) {
  return String(value || '')
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function addTag(map, tag, source, example = '') {
  const raw = String(tag || '').trim();
  if (!raw || raw.length > 40) return;
  if (/^\d+(\.\d+)?%?$/.test(raw)) return;
  if (/^\d{4}[-年]/.test(raw)) return;
  const key = tagNormalizer.keyOf(raw);
  if (!key) return;
  const row = map.get(key) || { raw_tag: raw, count: 0, sources: new Set(), examples: [] };
  row.count += 1;
  row.sources.add(source);
  if (example && row.examples.length < 5) row.examples.push(String(example).slice(0, 160));
  map.set(key, row);
}

function splitTagCell(text) {
  return String(text || '')
    .split(/[|,，、；;]/g)
    .map(x => x.trim())
    .filter(Boolean);
}

function collectFromHtml(file, tags) {
  const html = readText(file);
  if (!html) return;
  const industryCellMatches = html.match(/<td[^>]*class=["']?industry-tags["']?[^>]*>[\s\S]*?<\/td>/gi) || [];
  for (const cell of industryCellMatches) {
    const text = cleanHtml(cell);
    for (const part of splitTagCell(text)) addTag(tags, part, 'html-industry-cell', file);
  }
  const tagMatches = html.match(/<span[^>]*class=["'][^"']*industry-tag[^"']*["'][^>]*>[\s\S]*?<\/span>/gi) || [];
  for (const span of tagMatches) addTag(tags, cleanHtml(span), 'html-industry-tag', file);
  const plain = cleanHtml(html);
  const likely = plain.match(/(?:行业|题材|概念)[：:]\s*([^。；;\n\r]{2,80})/g) || [];
  for (const item of likely) {
    const text = item.replace(/^(行业|题材|概念)[：:]\s*/, '');
    for (const part of splitTagCell(text)) addTag(tags, part, 'html-plain-label', file);
  }
}

function collectPolicy(file, tags) {
  const json = readJson(file);
  for (const item of json?.top_industries || []) {
    addTag(tags, item.name, 'policy-top-industries', file);
  }
  for (const item of json?.scores || []) {
    addTag(tags, item.name, 'policy-score-dimension', file);
  }
}

function collectNews(file, tags) {
  const json = readJson(file);
  const items = json?.items || json?.top_industries || [];
  for (const item of items) {
    for (const field of ['name', 'title', 'summary', 'evidence']) {
      const text = String(item[field] || '');
      const candidates = text.match(/[A-Za-z0-9+\-]{2,20}|[\u4e00-\u9fa5]{2,12}/g) || [];
      for (const token of candidates) {
        if (/新闻|公司|市场|今日|昨日|公告|表示|亿元|同比|增长|下跌|上涨/.test(token)) continue;
        addTag(tags, token, `news-${field}`, text);
      }
    }
  }
}

function main() {
  const tags = new Map();
  const loadedRules = tagNormalizer.loadRules();
  const files = walk(ROOT).filter(file => /\.(html|json|md|txt)$/i.test(file));
  for (const file of files) {
    if (/node_modules|\.git/i.test(file)) continue;
    const stat = fs.statSync(file);
    if (stat.size > 300000 && !/policy_news_archive/i.test(file)) continue;
    if (/\.html$/i.test(file)) collectFromHtml(file, tags);
    else if (/policy_scores.*\.json$/i.test(file) || /policy_news_prefilter/i.test(file)) collectPolicy(file, tags);
    else if (/policy_news_archive/i.test(file)) {
      const archive = readJson(file);
      const limited = { items: (archive?.items || []).slice(0, 120) };
      const temp = path.join(TAG_DIR, '.policy_news_archive_recent.json');
      fs.writeFileSync(temp, JSON.stringify(limited), 'utf-8');
      collectNews(temp, tags);
      try { fs.unlinkSync(temp); } catch {}
    }
    else if (/tag_rules\.json$/i.test(file)) {
      const rules = readJson(file);
      for (const [canonical, aliases] of Object.entries(rules?.canonical_groups || {})) {
        addTag(tags, canonical, 'tag-rules-canonical', file);
        for (const alias of aliases || []) addTag(tags, alias, 'tag-rules-alias', file);
      }
    }
  }
  const rows = Array.from(tags.values()).map(row => ({
    raw_tag: row.raw_tag,
    count: row.count,
    sources: Array.from(row.sources),
    normalized: loadedRules.blocked.has(tagNormalizer.keyOf(row.raw_tag)) ? '已屏蔽' : tagNormalizer.normalizeTags([row.raw_tag], {
      trustedNewTags: [],
      context: { source: 'full-tag-collect', example: row.examples[0] || '' },
      limit: 1,
    })[0] || '',
    examples: row.examples,
  })).sort((a, b) => b.count - a.count || a.raw_tag.localeCompare(b.raw_tag, 'zh-CN'));

  const summary = {
    version: 1,
    updated_at: new Date().toISOString(),
    total_unique_tags: rows.length,
    mapped_count: rows.filter(row => row.normalized && row.normalized !== '已屏蔽').length,
    blocked_count: rows.filter(row => row.normalized === '已屏蔽').length,
    unmapped_count: rows.filter(row => !row.normalized).length,
    rows,
  };
  fs.mkdirSync(TAG_DIR, { recursive: true });
  fs.writeFileSync(path.join(TAG_DIR, 'all_tags_summary.json'), JSON.stringify(summary, null, 2), 'utf-8');
  const md = [
    '# 全量标签汇总',
    '',
    `更新时间：${summary.updated_at}`,
    `唯一原始标签数：${summary.total_unique_tags}`,
    `已映射：${summary.mapped_count}`,
    `已屏蔽噪声：${summary.blocked_count}`,
    `未映射：${summary.unmapped_count}`,
    '',
    '## 高频标签 Top 80',
    '',
    '| 原始标签 | 次数 | 当前统一标签 | 来源 |',
    '|---|---:|---|---|',
    ...rows.slice(0, 80).map(row => `| ${row.raw_tag} | ${row.count} | ${row.normalized || '待复核'} | ${row.sources.join(', ')} |`),
    '',
  ].join('\n');
  fs.writeFileSync(path.join(TAG_DIR, 'all_tags_summary.md'), md, 'utf-8');
  console.log(JSON.stringify({
    total_unique_tags: summary.total_unique_tags,
    mapped_count: summary.mapped_count,
    unmapped_count: summary.unmapped_count,
    output: path.join(TAG_DIR, 'all_tags_summary.json'),
  }, null, 2));
}

main();
