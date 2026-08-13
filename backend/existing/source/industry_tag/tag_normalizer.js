'use strict';

const fs = require('fs');
const path = require('path');

const RULE_FILE = path.join(__dirname, 'tag_rules.json');
const UNKNOWN_FILE = path.join(__dirname, 'unknown_tags_queue.json');

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf-8'));
  } catch {
    return fallback;
  }
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2), 'utf-8');
}

function keyOf(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/[()（）【】\[\]、，,；;|_\-·]/g, '')
    .trim();
}

function loadRules() {
  const rules = readJson(RULE_FILE, {});
  const aliasToCanonical = new Map();
  for (const [canonical, aliases] of Object.entries(rules.canonical_groups || {})) {
    aliasToCanonical.set(keyOf(canonical), canonical);
    for (const alias of aliases || []) {
      aliasToCanonical.set(keyOf(alias), canonical);
    }
  }
  const blocked = new Set((rules.blocked_tags || []).map(keyOf));
  return { rules, aliasToCanonical, blocked };
}

function splitTags(values) {
  const rows = Array.isArray(values) ? values : [values];
  return rows.flatMap(value => String(value || '').split(/[|,，、；;]/g))
    .map(value => value.trim())
    .filter(Boolean);
}

function appendUnknown(rawTag, context = {}) {
  const tag = String(rawTag || '').trim();
  const key = keyOf(tag);
  if (!tag || !key) return;
  const queue = readJson(UNKNOWN_FILE, { version: 1, updated_at: '', items: [] });
  queue.items = Array.isArray(queue.items) ? queue.items : [];
  const existing = queue.items.find(item => item.key === key);
  if (existing) {
    existing.count = (Number(existing.count) || 1) + 1;
    existing.last_seen_at = new Date().toISOString();
    if (context.source) existing.sources = Array.from(new Set([...(existing.sources || []), context.source]));
  } else {
    queue.items.push({
      key,
      raw_tag: tag,
      suggested_by: context.source || '',
      sources: context.source ? [context.source] : [],
      examples: context.example ? [String(context.example).slice(0, 160)] : [],
      count: 1,
      first_seen_at: new Date().toISOString(),
      last_seen_at: new Date().toISOString(),
      status: 'pending_deepseek_review'
    });
  }
  queue.updated_at = new Date().toISOString();
  queue.items.sort((a, b) => (b.count || 0) - (a.count || 0));
  writeJson(UNKNOWN_FILE, queue);
}

function normalizeTags(values, options = {}) {
  const { aliasToCanonical, blocked } = loadRules();
  const trustedNewTags = new Set(splitTags(options.trustedNewTags || []).map(keyOf));
  const output = [];
  const seen = new Set();
  for (const raw of splitTags(values)) {
    const key = keyOf(raw);
    if (!key || blocked.has(key)) continue;
    let canonical = aliasToCanonical.get(key);
    if (!canonical && trustedNewTags.has(key)) canonical = raw.trim();
    if (!canonical) {
      appendUnknown(raw, options.context || {});
      continue;
    }
    const canonicalKey = keyOf(canonical);
    if (seen.has(canonicalKey)) continue;
    seen.add(canonicalKey);
    output.push(canonical);
    if (output.length >= (options.limit || 12)) break;
  }
  return output;
}

function normalizeStockDetail(stockDetail, options = {}) {
  const detail = { ...(stockDetail || {}) };
  const tags = normalizeTags([
    detail.industry || '',
    ...(Array.isArray(detail.concepts) ? detail.concepts : [])
  ], options);
  detail.industry = tags[0] || detail.industry || '';
  detail.concepts = tags;
  return detail;
}

module.exports = {
  RULE_FILE,
  UNKNOWN_FILE,
  keyOf,
  normalizeTags,
  normalizeStockDetail,
  loadRules
};
