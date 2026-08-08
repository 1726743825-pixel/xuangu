#!/usr/bin/env node
/**
 * ============================================================
 *  超短线量化选股助手 v2.0
 *  总资金：7万元
 *  仅交易：沪市主板(600/601/603) + 深市主板(000/001/002) + 创业板(300/301)
 *  禁止：科创板(688) / 北交所(8/4/43) / ST
 * ============================================================
 *
 * 使用方法：
 *   node stock_screener.js
 *
 * 选股流程：
 *   硬门槛过滤 → 基础分计算(100分) → 加分项计算 → 扣分项计算 → 排序输出前十
 *
 * 数据源：
 *   a_stock_data_source.js（优先腾讯 / 百度股市通 / 东财限流方案）
 * ============================================================
 */
'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');      // 用于访问东方财富公开 API
const aStockData = require('./a_stock_data_source');

// ── 配置 ──
const TOTAL_FUNDS = 70000;               // 总资金 7 万元
const OUTPUT_FILE = 'D:/Program Files/xuangu/result/选股结果.html';
const MAX_CANDIDATES = Number.parseInt(process.env.MAX_CANDIDATES || '60', 10) || 60; // 最多详细分析的候选股
const KLINE_LIMIT = 150;                 // 获取 K 线天数（确保 MA60 有效）
const SDK_TIMEOUT = 30000;               // shell 命令超时(ms)

// ── 自动更新配置 ──
const SCRIPT_VERSION = '2.4.0';          // 当前版本号
const UPDATE_URL = 'https://gist.githubusercontent.com/1726743825-pixel/be9bfb4c401fbe9a6d10e56b344c2875/raw/stock_screener.js';
const AUTO_UPDATE_CHECK = false;         // 已切换为 a-stock-data 数据源，避免被旧 Gist 覆盖
// 检查日期：每月1-3日 和 15-17日（月初+月中）
const UPDATE_CHECK_DAYS = [[1,2,3], [15,16,17]];
const STOCK_DETAIL_FETCH_DELAY = 150;    // 东方财富详情请求间隔(ms)
const POLICY_SCORE_URL = 'https://gist.githubusercontent.com/1726743825-pixel/be9bfb4c401fbe9a6d10e56b344c2875/raw/policy_scores.json';
const LOCAL_POLICY_SCORE_FILE = 'D:/Program Files/xuangu/policy_scores.json';
const POLICY_FETCH_TIMEOUT = 15000;

// ── 工具函数 ──

function run(cmd, timeout = SDK_TIMEOUT) {
  try {
    const out = execSync(cmd, { timeout, encoding: 'utf-8', stdio: ['pipe','pipe','pipe'] });
    return out.trim();
  } catch (e) {
    return null;
  }
}

function runJSON(cmd, timeout = SDK_TIMEOUT) {
  const out = run(cmd, timeout);
  if (!out) return null;
  try {
    // 找到第一个 [ 或 { 开始的位置
    const start = out.search(/[\[{]/);
    return start >= 0 ? JSON.parse(out.slice(start)) : null;
  } catch { return null; }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function compareVersions(a, b) {
  const left = String(a || '').split('.').map(x => Number.parseInt(x, 10) || 0);
  const right = String(b || '').split('.').map(x => Number.parseInt(x, 10) || 0);
  const len = Math.max(left.length, right.length);

  for (let i = 0; i < len; i++) {
    const diff = (left[i] || 0) - (right[i] || 0);
    if (diff !== 0) return diff;
  }

  return 0;
}

// ── 东方财富 API 域名配置（主备）── v2.3.0
const EM_PRIMARY = 'push2.eastmoney.com';
const EM_BACKUP = 'push2delay.eastmoney.com';

// ── 东方财富公开 API HTTPS 请求工具 ──

/**
 * 通用 HTTPS GET 请求，内置 10 秒超时，失败返回 null
 * 使用 Node.js 内置 https 模块，零外部依赖
 * v2.3.0: 新增备用域名自动重试
 */
function httpGet(url, useBackup = false) {
  return new Promise((resolve) => {
    let finalUrl = url;
    if (useBackup) {
      finalUrl = url.replace(EM_PRIMARY, EM_BACKUP);
    }
    const req = https.get(finalUrl, {
      timeout: 10000,
      rejectUnauthorized: false,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://quote.eastmoney.com/'
      }
    }, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    });
    req.on('error', (e) => {
      if (!useBackup) {
        console.log(`  ⚠️ 主域名请求失败: ${e.message}，尝试备用域名...`);
        httpGet(url, true).then(resolve);
      } else {
        console.log(`  ❌ 备用域名也失败: ${e.message}`);
        resolve(null);
      }
    });
    req.on('timeout', () => { 
      req.destroy(); 
      if (!useBackup) {
        console.log('  ⚠️ 主域名请求超时，尝试备用域名...');
        httpGet(url, true).then(resolve);
      } else {
        resolve(null);
      }
    });
  });
}

/** 获取东方财富 JSON 接口（自动 parse） */
async function httpGetJSON(url) {
  const raw = await httpGet(url);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

function readJSONFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    return null;
  }
}

function writeJSONFile(filePath, data) {
  try {
    fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf-8');
    return true;
  } catch {
    return false;
  }
}

function fetchTextByCurl(url, timeout = POLICY_FETCH_TIMEOUT) {
  try {
    return execSync(
      `curl -sL --max-time ${Math.max(1, Math.floor(timeout / 1000))} "${url}"`,
      { timeout, encoding: 'utf-8', stdio: ['pipe', 'pipe', 'pipe'] }
    ).trim();
  } catch {
    return null;
  }
}

function parsePolicyScoreConfig(raw) {
  if (!raw) return null;
  try {
    const config = JSON.parse(raw);
    return Array.isArray(config?.scores) ? config : null;
  } catch {
    return null;
  }
}

function readLocalPolicyScoreConfig() {
  const config = readJSONFile(LOCAL_POLICY_SCORE_FILE);
  return Array.isArray(config?.scores) ? config : null;
}

function fetchPolicyScoreConfig() {
  const remoteUrls = [...new Set([POLICY_SCORE_URL, UPDATE_URL])];

  for (const url of remoteUrls) {
    const remoteConfig = parsePolicyScoreConfig(fetchTextByCurl(url));
    if (!remoteConfig) continue;

    writeJSONFile(LOCAL_POLICY_SCORE_FILE, remoteConfig);
    return {
      config: remoteConfig,
      source: url === POLICY_SCORE_URL ? 'gist' : 'legacy-gist',
      url,
    };
  }

  const localConfig = readLocalPolicyScoreConfig();
  if (localConfig) {
    return {
      config: localConfig,
      source: 'local-cache',
      url: LOCAL_POLICY_SCORE_FILE,
    };
  }

  return {
    config: null,
    source: 'default',
    url: null,
  };
}

function getDefaultCertaintyScores() {
  return [
    // 一、政策维度 (最高3.0分)
    { name: '国家战略支持', max: 1.5, value: 0, detail: '如本月:低空/6G/量子计算' },
    { name: '地方配套政策', max: 1.5, value: 0, detail: '如地方补贴/项目支持' },
    // 二、资金维度 (最高4.0分)
    { name: '机构持仓变动', max: 1.0, value: 0, detail: '公募/社保/险资环比>1%' },
    { name: '主力资金/ETF流入', max: 1.0, value: 0, detail: '近1月流入前10%' },
    { name: '公司回购/分红', max: 1.0, value: 0, detail: '注册制回购/分红>3%' },
    { name: '高股息持续性', max: 1.0, value: 0, detail: '近3年分红稳定' },
    // 三、基本面维度 (最高4.5分)
    { name: '业绩超预期', max: 1.5, value: 0, detail: '增长超预期>20%' },
    { name: '盈利能力趋势', max: 1.5, value: 0, detail: '毛利率/净利率环比提升' },
    { name: '订单/合同增长', max: 1.5, value: 0, detail: '新签订单同比>30%' },
    // 四、产业竞争力维度 (最高3.5分)
    { name: '研发强度', max: 1.0, value: 0, detail: '专利前10%/研发>10%' },
    { name: '产业地位', max: 1.0, value: 0, detail: '细分领域龙头/潜在龙头' },
    { name: '产业落地进度', max: 1.5, value: 0, detail: '已规模商用/试点阶段' },
  ];
}

const THEME_ALIAS_MAP = {
  '低空经济': ['低空', 'eVTOL', '飞行汽车', '无人机', '通用航空', '飞行器', '航空装备'],
  '半导体/芯片': ['半导体', '芯片', '集成电路', '电子化学品', '光刻', '封测', '存储', 'AI芯片', '第三代半导体'],
  '新型能源体系': ['新型能源', '新能源', '光伏', '储能', '风电', '氢能', '电池', '电力', '特高压', '充电桩', '新能源车', '汽车热管理', '燃料电池'],
  '人工智能/AI大模型': ['人工智能', 'AI', 'AIGC', '大模型', '算力', 'CPO', '数据中心', '机器人', '机器视觉', '智驾', '自动驾驶', '人形机器人'],
  '工业互联网/6G': ['工业互联网', '工业互联', '工业5G', '6G', '5G', '通信设备', '物联网', '智能制造', '自动化设备', '工业母机'],
};

function round1(value) {
  return Math.round((Number(value) || 0) * 10) / 10;
}

function normalizeThemeText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[\s\-_/\\|（）()·,.，:+&]/g, '')
    .trim();
}

function getThemeAliases(themeName) {
  const aliases = new Set();
  const sourceParts = [themeName, ...(THEME_ALIAS_MAP[themeName] || [])];

  for (const part of sourceParts) {
    for (const token of String(part || '').split(/[\/、,，\s]+/)) {
      const text = token.trim();
      if (text) aliases.add(text);
    }
  }

  return Array.from(aliases);
}

function buildCertaintyScores(policyConfig) {
  const defaults = getDefaultCertaintyScores();
  const remoteScoreMap = new Map(
    (policyConfig?.scores || [])
      .filter(item => item && item.name)
      .map(item => [item.name, item])
  );

  return defaults.map(item => {
    const remoteItem = remoteScoreMap.get(item.name);
    if (!remoteItem) return { ...item };

    return {
      ...item,
      max: typeof remoteItem.max === 'number' ? remoteItem.max : item.max,
      value: typeof remoteItem.value === 'number' ? remoteItem.value : item.value,
      detail: remoteItem.detail || item.detail,
    };
  });
}

function buildThemeProfiles(policyConfig) {
  const themes = Array.isArray(policyConfig?.top_industries)
    ? policyConfig.top_industries.filter(item => item && item.name)
    : [];
  const maxThemeScore = themes.reduce((max, item) => Math.max(max, Number(item.score) || 0), 0) || 100;

  return {
    maxThemeScore,
    themes: themes.map(theme => {
      const aliases = getThemeAliases(theme.name);
      const aliasProfiles = aliases.map(alias => ({
        raw: alias,
        normalized: normalizeThemeText(alias),
      })).filter(item => item.normalized);

      return {
        ...theme,
        score: Number(theme.score) || 0,
        aliasProfiles,
      };
    }),
  };
}

function findAliasHits(featureText, aliasProfiles) {
  const normalizedFeature = normalizeThemeText(featureText);
  if (!normalizedFeature) return [];

  return aliasProfiles.filter(alias =>
    normalizedFeature.includes(alias.normalized) ||
    alias.normalized.includes(normalizedFeature)
  );
}

function calcCertaintyBonus(policyConfig, stockDetail, fallbackIndustry) {
  const certaintyScores = buildCertaintyScores(policyConfig);
  const certaintyPool = round1(certaintyScores.reduce(
    (sum, item) => sum + Math.min(Math.max(Number(item.value) || 0, 0), Number(item.max) || 0),
    0,
  ));
  if (certaintyPool <= 0) {
    return { score: 0, detail: '本月确定性加分池为0', matchedThemes: [] };
  }

  const { themes, maxThemeScore } = buildThemeProfiles(policyConfig);
  if (themes.length === 0) {
    return { score: 0, detail: '未配置 top_industries', matchedThemes: [] };
  }

  const industry = stockDetail?.industry || fallbackIndustry || '';
  const concepts = Array.isArray(stockDetail?.concepts) ? stockDetail.concepts : [];
  const matchedThemes = [];

  for (const theme of themes) {
    const industryHits = findAliasHits(industry, theme.aliasProfiles);
    const conceptMatches = [];

    for (const concept of concepts) {
      const hits = findAliasHits(concept, theme.aliasProfiles);
      if (hits.length > 0) {
        conceptMatches.push({
          concept,
          alias: hits[0].raw,
        });
      }
    }

    const uniqueConceptMatches = conceptMatches.filter((item, index, arr) =>
      arr.findIndex(x => x.concept === item.concept) === index
    );

    let matchStrength = 0;
    if (industryHits.length > 0) {
      matchStrength = 1;
    } else if (uniqueConceptMatches.length > 0) {
      matchStrength = Math.min(0.85, 0.55 + (uniqueConceptMatches.length - 1) * 0.15);
    }

    if (industryHits.length > 0 && uniqueConceptMatches.length > 0) {
      matchStrength = 1;
    }

    const themeFactor = matchStrength > 0
      ? (theme.score / maxThemeScore) * matchStrength
      : 0;

    if (themeFactor > 0) {
      matchedThemes.push({
        name: theme.name,
        level: theme.level || '',
        score: theme.score,
        matchStrength,
        themeFactor,
        industryHit: industryHits.length > 0,
        conceptMatches: uniqueConceptMatches,
      });
    }
  }

  if (matchedThemes.length === 0) {
    return { score: 0, detail: '未命中本月重点行业题材', matchedThemes: [] };
  }

  matchedThemes.sort((a, b) => b.themeFactor - a.themeFactor);
  const [primaryTheme, secondaryTheme] = matchedThemes;
  const exposureFactor = Math.min(1, primaryTheme.themeFactor + (secondaryTheme?.themeFactor || 0) * 0.35);
  const certaintyBonus = round1(certaintyPool * exposureFactor);

  const matchedThemeSummary = matchedThemes.slice(0, 2).map(theme => {
    const hitParts = [];
    if (theme.industryHit && industry) hitParts.push(`行业:${industry}`);
    if (theme.conceptMatches.length > 0) {
      hitParts.push(`概念:${theme.conceptMatches.slice(0, 2).map(item => item.concept).join('/')}`);
    }
    return `${theme.name}${theme.level ? `[${theme.level}]` : ''}${hitParts.length ? `(${hitParts.join(',')})` : ''}`;
  }).join('；');

  return {
    score: certaintyBonus,
    detail: `${matchedThemeSummary}；主题系数${round1(exposureFactor)}`,
    matchedThemes,
  };
}

// ── 大盘数据 ──

/**
 * 获取上证指数实时行情 + 全市场涨跌家数
 * URL: https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001
 * 关键字段：f170=涨跌幅(×100), f43=最新价(×100), f113=上涨家数, f114=下跌家数
 * 返回: { sseChangePercent, advDeclRatio, price, riseCount, fallCount } 或 null
 */
async function getMarketData() {
  return aStockData.getMarketData();
}

// ── 板块热点数据 ──

/**
 * 获取行业板块列表（东方财富）
 * URL: https://push2.eastmoney.com/api/qt/clist/get
 * 关键字段：f12=板块代码, f14=板块名称, f3=涨跌幅%, f86=上涨家数, f87=下跌家数
 * 返回: [{ bkCode, name, changePercent, riseCount, fallCount }] 按涨跌幅降序
 */
async function getSectorList() {
  return aStockData.getSectorList();
}

async function getConceptList() {
  return aStockData.getConceptList();
}

/**
 * 获取某行业板块的成分股列表
 * URL: https://push2.eastmoney.com/api/qt/clist/get?fs=b:{sectorCode}
 * 返回: [{ code, name, changePercent }] 按涨幅降序
 */
async function getSectorConstituents(sectorCode) {
  return aStockData.getSectorConstituents(sectorCode);
}

/** 行业名称 → BK代码 缓存 */
let _sectorNameMap = null;
async function getSectorNameMap() {
  if (_sectorNameMap) return _sectorNameMap;
  const list = await getSectorList();
  if (!list) return null;
  _sectorNameMap = {};
  for (const s of list) _sectorNameMap[s.name] = s.bkCode;
  return _sectorNameMap;
}

/**
 * 匹配个股所属行业板块
 * 根据 stock.industry（如"元件"）查找对应的 BK 代码
 */
async function matchSector(stockIndustry) {
  if (!stockIndustry) return null;
  const map = await getSectorNameMap();
  if (!map) return null;
  const bkCode = map[stockIndustry];
  if (!bkCode) return null;
  // 获取该板块在行业列表中的排名
  const list = await getSectorList();
  if (!list) return null;
  const idx = list.findIndex(s => s.bkCode === bkCode);
  if (idx < 0) return null;
  return {
    bkCode,
    rank: idx + 1,
    total: list.length,
    sector: list[idx],
  };
}

// ── 个股详情（资金流向 + 行业） ──

/**
 * 获取个股详情：资金流向 + 行业归属
 * URL: https://push2.eastmoney.com/api/qt/stock/get
 * secid: 0=深市, 1=沪市
 * 关键字段：f184=主力净流入占比%, f187=大单净流入占比%, f62=主力净流入(元),
 *          f66=大单净流入(元), f170=涨跌幅(×100)
 * 返回: { code, name, mainForcePercent, largeOrderPercent, ... } 或 null
 */
async function getStockDetail(code) {
  return aStockData.getStockDetail(code);
}

// ── 涨停溢价 ──

/**
 * 计算昨日涨停股今日的平均涨幅（涨停溢价）
 * BK0815 = 东方财富"昨日涨停"概念板块
 * 返回: 平均涨跌幅%（如 -0.85）
 */
async function getZTPremium() {
  return aStockData.getZTPremium();
}

// ── 批量构建板块评分数据 ──

/**
 * 为所有候选股批量构建板块信息
 * 1. 获取行业板块列表 → name→bkCode 映射
 * 2. 对每只股票，找到其行业板块的排名、涨停数、个股排名
 * 返回: Map(code → { sectorRankPercent, sectorLimitUpCount, stockRankPercent, sectorChangePercent })
 */
function normalizeIndustryName(value) {
  return String(value || '')
    .replace(/\s+/g, '')
    .replace(/[()（）\-·]/g, '')
    .trim();
}

function resolveSectorCode(industryName, nameToBK, industries) {
  if (!industryName) return null;
  if (nameToBK[industryName]) return nameToBK[industryName];

  const normalized = normalizeIndustryName(industryName);
  if (!normalized) return null;

  const exact = industries.find(ind => normalizeIndustryName(ind.name) === normalized);
  if (exact) return exact.bkCode;

  const prefixMatches = industries.filter(ind => {
    const sectorName = normalizeIndustryName(ind.name);
    return sectorName.startsWith(normalized) || normalized.startsWith(sectorName);
  });
  if (prefixMatches.length > 0) {
    prefixMatches.sort((a, b) => normalizeIndustryName(a.name).length - normalizeIndustryName(b.name).length);
    return prefixMatches[0].bkCode;
  }

  const fuzzyMatches = industries.filter(ind => {
    const sectorName = normalizeIndustryName(ind.name);
    return sectorName.includes(normalized) || normalized.includes(sectorName);
  });
  if (fuzzyMatches.length > 0) {
    fuzzyMatches.sort((a, b) => normalizeIndustryName(a.name).length - normalizeIndustryName(b.name).length);
    return fuzzyMatches[0].bkCode;
  }

  return null;
}

async function buildStockDetailMap(candidates) {
  const detailMap = {};

  for (let i = 0; i < candidates.length; i++) {
    const stock = candidates[i];
    const detail = await getStockDetail(stock.code);
    if (detail) detailMap[stock.code] = detail;
    if (i < candidates.length - 1) await sleep(STOCK_DETAIL_FETCH_DELAY);
  }

  return detailMap;
}

async function buildSectorInfo(candidates, stockDetailMap = {}) {
  const [industries, concepts] = await Promise.all([
    getSectorList(),
    getConceptList(),
  ]);
  if (!industries) return null;

  const industryNameToBK = {};
  for (const ind of industries) industryNameToBK[ind.name] = ind.bkCode;

  const conceptNameToBK = {};
  for (const concept of concepts || []) conceptNameToBK[concept.name] = concept.bkCode;

  const bkCache = {};
  const result = {};

  for (const stock of candidates) {
    const detail = stockDetailMap[stock.code] || {};
    const detailIndustry = detail.industry;
    const detailConcepts = detail.concepts || [];
    const indName = detailIndustry || stock.industry;

    const boardCandidates = [];
    const industryCode = resolveSectorCode(indName, industryNameToBK, industries);
    if (industryCode) {
      boardCandidates.push({
        bkCode: industryCode,
        boardList: industries,
      });
    }

    for (const conceptName of detailConcepts) {
      const conceptCode = resolveSectorCode(conceptName, conceptNameToBK, concepts || []);
      if (!conceptCode) continue;
      if (boardCandidates.some(item => item.bkCode === conceptCode)) continue;
      boardCandidates.push({
        bkCode: conceptCode,
        boardList: concepts || [],
      });
    }

    for (const board of boardCandidates) {
      const boardInfo = board.boardList.find(x => x.bkCode === board.bkCode);
      if (!boardInfo) continue;

      if (!bkCache[board.bkCode]) {
        bkCache[board.bkCode] = await getSectorConstituents(board.bkCode);
        await sleep(500); // v2.3.0: 防反爬
      }
      const constituents = bkCache[board.bkCode];
      if (!constituents) continue;

      const sectorRank = board.boardList.findIndex(x => x.bkCode === board.bkCode) + 1;
      const sectorRankPercent = (sectorRank / board.boardList.length) * 100;
      const limitUpCount = constituents.filter(s => s.changePercent >= 9.5).length;
      const stockIdx = constituents.findIndex(s => s.code === stock.code);
      const stockRankPercent = stockIdx >= 0 ? ((stockIdx + 1) / constituents.length) * 100 : 50;

      result[stock.code] = {
        sectorRankPercent,
        sectorLimitUpCount: limitUpCount,
        stockRankPercent,
        sectorChangePercent: boardInfo.changePercent,
      };
      break;
    }
  }

  return result;
}

function todayStr() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2,'0');
  const day = String(d.getDate()).padStart(2,'0');
  return `${y}${m}${day}`;
}

function formatDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2,'0');
  const day = String(d.getDate()).padStart(2,'0');
  return `${y}-${m}-${day}`;
}

function determineLevelAndSuggestion(finalScore) {
  if (finalScore >= 75) {
    return { level: 'A', suggestion: '强势共振，可出手，仓位3-4成' };
  }
  if (finalScore >= 68) {
    return { level: 'B', suggestion: '轻仓试错1-2成' };
  }
  if (finalScore >= 60) {
    return { level: 'C', suggestion: '观察名单，暂不出手' };
  }
  return { level: 'D', suggestion: '放弃' };
}

// ── 板块判断 ──

function getBoard(code) {
  if (!code || code.length < 6) return 'unknown';
  if (code.startsWith('600') || code.startsWith('601') || code.startsWith('603')) return 'sh_main';
  if (code.startsWith('000') || code.startsWith('001') || code.startsWith('002')) return 'sz_main';
  if (code.startsWith('300') || code.startsWith('301')) return 'sz_chinext';
  if (code.startsWith('688')) return 'sh_star';
  if (code.startsWith('8') || code.startsWith('4') || code.startsWith('43')) return 'bj';
  return 'other';
}

function isAllowed(code, name) {
  const board = getBoard(code);
  if (board !== 'sh_main' && board !== 'sz_main' && board !== 'sz_chinext') return false;
  if (name && (name.includes('ST') || name.includes('*ST'))) return false;
  return true;
}

// ── 自动更新检查 ──

function shouldCheckUpdate() {
  if (!AUTO_UPDATE_CHECK || !UPDATE_URL) return false;
  const now = new Date();
  const day = now.getDate();
  return UPDATE_CHECK_DAYS.some(group => group.includes(day));
}

async function checkUpdate(silent = false) {
  if (!UPDATE_URL) {
    if (!silent) console.log('  ℹ️  未配置更新源(UPDATE_URL)，跳过自动更新');
    return;
  }
  if (!shouldCheckUpdate()) return;

  try {
    const remote = execSync(
      `curl -sL --max-time 10 "${UPDATE_URL}"`,
      { timeout: 15000, encoding: 'utf-8', stdio: ['pipe','pipe','pipe'] }
    ).trim();
    // 从远程脚本中提取版本号
    const m = remote.match(/const SCRIPT_VERSION\s*=\s*['"]([^'"]+)['"]/);
    if (!m) { if (!silent) console.log('  ⚠️  远程脚本版本格式异常'); return; }

    const remoteVer = m[1];
    const versionDiff = compareVersions(remoteVer, SCRIPT_VERSION);
    if (versionDiff > 0) {
      console.log(`  📥 发现新版本 ${remoteVer} (当前 ${SCRIPT_VERSION})，正在更新...`);
      // 备份当前脚本
      const selfPath = process.argv[1] || __filename;
      fs.writeFileSync(selfPath + '.bak', fs.readFileSync(selfPath), 'utf-8');
      // 写回新版本
      fs.writeFileSync(selfPath, remote, 'utf-8');
      console.log(`  ✅ 已更新至 ${remoteVer}，旧版备份至 ${path.basename(selfPath)}.bak`);
      console.log(`  🔄 请重新运行脚本以使用新版本`);
      process.exit(0);
    } else if (versionDiff < 0) {
      if (!silent) console.log(`  [update] skip older remote version ${remoteVer} < ${SCRIPT_VERSION}`);
    } else {
      if (!silent) console.log(`  ✅ 已是最新版本 ${SCRIPT_VERSION}`);
    }
  } catch (e) {
    if (!silent) console.log(`  ⚠️  检查更新失败: ${e.message.slice(0, 60)}`);
  }
}

// ── 一字板检测（扣分项5）──
function checkLimitUpBreak(stock, klines) {
  if (klines.length < 5) return null;
  const last5 = klines.slice(-5);
  let consecutiveYiZi = 0;
  for (let i = last5.length - 2; i >= 0; i--) {
    const k = last5[i];
    const isYiZi = Math.abs(k.changePercent - 10) < 0.5 && Math.abs(k.open - k.close) < 0.01;
    if (isYiZi) consecutiveYiZi++; else break;
  }
  if (consecutiveYiZi < 2) return null;
  const today = last5[last5.length - 1], yesterday = last5[last5.length - 2];
  const todayNotYiZi = Math.abs(today.open - today.close) > 0.05 || Math.abs(today.changePercent - 10) >= 0.5;
  const volumeBurst = today.volume > yesterday.volume * 3;
  if (todayNotYiZi && volumeBurst) return { name: '一字板后首次开板放量', score: -5, detail: `连续${consecutiveYiZi}日一字板，今日量${(today.volume/yesterday.volume).toFixed(1)}x` };
  return null;
}

// ── 涨停失败/炸板近似检测（扣分项6）──
function checkFailedLimitUp(stock, klines) {
  const today = klines[klines.length - 1];
  const touchedLimit = today.high >= today.open * 1.095;
  const closedNotLimit = today.changePercent < 9.5;
  const body = Math.abs(today.close - today.open);
  const longUpperShadow = body > 0 && (today.high - Math.max(today.close, today.open)) / body > 1;
  if (touchedLimit && closedNotLimit && longUpperShadow) return { name: '涨停失败(炸板近似)', score: -4, detail: `触及涨停但收盘${today.changePercent.toFixed(2)}%，长上影` };
  return null;
}

// ── 龙虎榜散户霸榜检测（扣分项8）── 东财拉萨系席位
const RETAIL_SEATS = ['拉萨', '东方财富证券股份有限公司拉萨'];

async function checkDragonTigerRetail(code) {
  return aStockData.checkDragonTigerRetail(code);
}

// ── 前高附近双顶嫌疑检测（扣分项10）──
function checkDoubleTop(stock, klines) {
  if (klines.length < 30) return null;
  const last30 = klines.slice(-30);
  const today = last30[last30.length - 1];
  let prevHighPrice = 0, prevHighIdx = -1;
  for (let i = 0; i < last30.length - 1; i++) {
    if (last30[i].high > prevHighPrice) { prevHighPrice = last30[i].high; prevHighIdx = i; }
  }
  if (prevHighIdx < 0) return null;
  const prevHigh = last30[prevHighIdx];
  if (today.high >= prevHighPrice * 0.98 && today.volume > prevHigh.volume && today.changePercent < prevHigh.changePercent * 0.5) {
    return { name: '前高附近双顶嫌疑', score: -4, detail: `触及前高${prevHighPrice.toFixed(2)}，量增但涨幅${today.changePercent.toFixed(1)}%<前次${prevHigh.changePercent.toFixed(1)}%一半` };
  }
  return null;
}

// ── 股东减持/解禁检测（扣分项11）──
async function checkAnnouncementRisk(code) {
  return aStockData.checkAnnouncementRisk(code);
}

// ── 数据获取 ──

/** 获取涨停/强势股池 */
async function getCandidates() {
  console.log('📡 获取涨停股池...');
  const state = await aStockData.getCandidates();
  const candidates = (state.candidates || []).filter(s => isAllowed(s.code, s.name));
  console.log(`  ✅ a-stock-data 原始候选：${(state.candidates || []).length} 只`);
  console.log(`  ✅ 过滤后候选：${candidates.length} 只`);
  return { candidates, yesterdayPool: state.yesterdayPool || [] };
}

/** 获取个股技术指标 K 线（a-stock-data：百度股市通日线 + 本地补 MA60/MACD/KDJ） */
async function getIndicators(code) {
  return aStockData.getIndicators(code, KLINE_LIMIT);
}

/** 获取个股行情 */
async function getQuote(code) {
  return aStockData.getQuote(code);
}

// ── 硬门槛检查 ──

function checkHardFilters(stock, klines) {
  if (klines.length < 60) return { pass: false, reason: 'K线数据不足(<60天)' };

  // 取最新一条 K 线
  const latest = klines[klines.length - 1];
  const prev60 = klines.slice(-60);

  // 1. 非 ST（已在外层过滤）
  // 2. 非科创板/北交所（创业板已放开，已在外层过滤）

  // 3. 非下跌趋势：60日均线方向向上，或当前股价 > 60日均线；近期高点未不断降低
  const ma60Values = prev60.map(k => k.ma?.ma60).filter(v => v != null);
  if (ma60Values.length < 10) return { pass: false, reason: 'MA60 数据不足' };

  // MA60 方向：比较最近期与早期
  const ma60Recent = ma60Values.slice(-5).reduce((a,b) => a + b, 0) / 5;
  const ma60Early = ma60Values.slice(0, 5).reduce((a,b) => a + b, 0) / 5;
  const ma60Up = ma60Recent > ma60Early * 1.001; // 方向向上
  const priceAboveMA60 = latest.close > ma60Values[ma60Values.length - 1];

  if (!ma60Up && !priceAboveMA60) {
    return { pass: false, reason: `下跌趋势(MA60方向${ma60Up ? '↑' : '↓'},股价${priceAboveMA60 ? '>' : '<'}MA60)` };
  }

  // 检查近期高点未不断降低（近20日高点趋势）
  const high10 = klines.slice(-10).map(k => k.high).filter(v => v != null); // v2.3.0: 改为10日
  if (high10.length >= 8) {
    const recentHigh = Math.max(...high10.slice(-5));
    const earlierHigh = Math.max(...high10.slice(0, 5));
    if (recentHigh < earlierHigh * 0.95) {
      return { pass: false, reason: `近期高点不断降低(近5日高${recentHigh.toFixed(2)}<前期${earlierHigh.toFixed(2)})` };
    }
  }

  // 4. 均线多头排列：MA5 > MA10 > MA20 > MA60，且四条均线方向均向上
  const ma5 = latest.ma?.ma5;
  const ma10 = latest.ma?.ma10;
  const ma20 = latest.ma?.ma20;
  const ma60 = latest.ma?.ma60;

  if (ma5 == null || ma10 == null || ma20 == null || ma60 == null) {
    return { pass: false, reason: '均线数据不完整' };
  }

  // 检查 MA 方向（最近 5 天递增）
  const getMaTrend = (key) => {
    const vals = klines.slice(-5).map(k => k.ma?.[key]).filter(v => v != null);
    if (vals.length < 3) return false;
    return vals[vals.length - 1] > vals[0] * 0.998;
  };

  const ma5Up = getMaTrend('ma5');
  const ma10Up = getMaTrend('ma10');
  const ma20Up = getMaTrend('ma20');
  const ma60Up2 = getMaTrend('ma60');

  if (!(ma5 > ma10 && ma10 > ma20 && ma20 > ma60)) {
    return { pass: false, reason: `非多头排列(MA5=${ma5.toFixed(2)},MA10=${ma10.toFixed(2)},MA20=${ma20.toFixed(2)},MA60=${ma60.toFixed(2)})` };
  }

  if (!(ma5Up && ma10Up && ma20Up && ma60Up2)) {
    return { pass: false, reason: `均线方向未全部向上(MA5${ma5Up?'↑':'↓'} MA10${ma10Up?'↑':'↓'} MA20${ma20Up?'↑':'↓'} MA60${ma60Up2?'↑':'↓'})` };
  }

  return { pass: true, reason: '' };
}

// ── 基础分计算 (100 分) — 线性百分比分配 ──
// 通用公式: 得分 = (实际值 - 零分阈值) / (满分阈值 - 零分阈值) × 满分
// 低于零分阈值=0分, 高于满分阈值=满分

function calcBaseScore(stock, klines, quote, sectorInfo, conceptInfo, marketInfo, flowInfo) {
  const latest = klines[klines.length - 1];
  const prev = klines.length >= 2 ? klines[klines.length - 2] : latest;

  const c = latest.close;
  const o = latest.open;
  const h = latest.high;
  const l = latest.low;
  const v = latest.volume || 0;
  const chgPct = latest.changePercent || 0;

  const ma5 = latest.ma?.ma5;
  const ma10 = latest.ma?.ma10;
  const ma20 = latest.ma?.ma20;
  const ma60 = latest.ma?.ma60;

  const dif = latest.macd?.dif;
  const dea = latest.macd?.dea;
  const macdVal = latest.macd?.macd;

  const kVal = latest.kdj?.k;
  const dVal = latest.kdj?.d;
  const jVal = latest.kdj?.j;

  let scores = {};
  let details = [];

  // 线性插值辅助函数
  const linear = (val, vMin, vMax, maxScore) => {
    if (val == null || isNaN(val)) return 0;
    if (vMin === vMax) return val >= vMin ? maxScore : 0;
    if (vMin <= vMax) {
      // 正向：值越大分越高
      if (val <= vMin) return 0;
      if (val >= vMax) return maxScore;
      return ((val - vMin) / (vMax - vMin)) * maxScore;
    } else {
      // 反向：值越小分越高 (vMin > vMax)
      if (val >= vMin) return 0;
      if (val <= vMax) return maxScore;
      return ((vMin - val) / (vMin - vMax)) * maxScore;
    }
  };
  const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

  // ── 一、均线强度 (12 分) ──

  // 1.1 MA5>MA10 开口率 (4 分): V_min=0%, V_max=3%
  let score_ma1 = 0;
  if (ma5 && ma10 && ma5 > ma10) {
    const gap = ((ma5 - ma10) / ma10) * 100; // 百分比
    score_ma1 = linear(gap, 0, 3, 4);
  }
  scores.ma1 = { score: score_ma1, max: 4, name: 'MA5>MA10开口率', detail: ma5&&ma10 ? `${((ma5-ma10)/ma10*100).toFixed(2)}%` : 'N/A' };
  details.push(`MA5开口: ${score_ma1.toFixed(1)}/4`);

  // 1.2 股价>MA5 偏离率 (4 分): V_min=0%, V_max=2%
  let score_ma2 = 0;
  if (c && ma5 && c > ma5) {
    const dev = ((c - ma5) / ma5) * 100;
    score_ma2 = linear(dev, 0, 3, 4); // v2.3.0: 满分阈值从2%改为3%
  }
  scores.ma2 = { score: score_ma2, max: 4, name: '股价>MA5偏离率', detail: c&&ma5 ? `${((c-ma5)/ma5*100).toFixed(2)}%` : 'N/A' };
  details.push(`MA5偏离: ${score_ma2.toFixed(1)}/4`);

  // 1.3 MA20>MA60 开口率 (4 分): V_min=0%, V_max=5%
  let score_ma3 = 0;
  if (ma20 && ma60 && ma20 > ma60) {
    const gap = ((ma20 - ma60) / ma60) * 100;
    score_ma3 = linear(gap, 0, 5, 4);
  }
  scores.ma3 = { score: score_ma3, max: 4, name: 'MA20>MA60开口率', detail: ma20&&ma60 ? `${((ma20-ma60)/ma60*100).toFixed(2)}%` : 'N/A' };
  details.push(`MA20开口: ${score_ma3.toFixed(1)}/4`);

  // ── 二、MACD 动能 (13 分) ──

  // 2.1 DIF-DEA 差值 (4 分): V_min=0, V_max=0.5
  // DIF≤DEA得0；DIF>DEA且DIF<0时最高2分
  let score_macd1 = 0;
  if (dif != null && dea != null && dif > dea) {
    const diffVal = dif - dea;
    if (dif < 0) {
      // 零轴下最高2分
      score_macd1 = Math.min(2, linear(diffVal, 0, 0.3, 2));
    } else {
      score_macd1 = linear(diffVal, 0, 0.5, 4);
    }
  }
  scores.macd1 = { score: score_macd1, max: 4, name: 'DIF-DEA差值', detail: dif!=null&&dea!=null ? (dif-dea).toFixed(3) : 'N/A' };
  details.push(`DIF-DEA: ${score_macd1.toFixed(1)}/4`);

  // 2.2 MACD 柱变化量 (4 分): V_min=-0.2, V_max=0.3
  // 今日柱≤0得0
  let score_macd2 = 0;
  if (macdVal != null && macdVal > 0 && prev.macd?.macd != null) {
    const change = macdVal - prev.macd.macd;
    score_macd2 = linear(change, -0.2, 0.3, 4);
  }
  scores.macd2 = { score: score_macd2, max: 4, name: 'MACD柱变化', detail: macdVal!=null&&prev.macd?.macd!=null ? (macdVal-prev.macd.macd).toFixed(3) : 'N/A' };
  details.push(`MACD柱: ${score_macd2.toFixed(1)}/4`);

  // 2.3 近3日金叉 (5 分) — 保持阶梯式不变
  let score_macd3 = 0;
  if (dif != null && dea != null) {
    let recentCross = false;
    for (let i = klines.length - 3; i < klines.length - 1 && i >= 0; i++) {
      const k1 = klines[i];
      const k2 = klines[i + 1];
      if (k1.macd?.dif != null && k1.macd?.dea != null && k2.macd?.dif != null && k2.macd?.dea != null) {
        if (k1.macd.dif <= k1.macd.dea && k2.macd.dif > k2.macd.dea) {
          recentCross = true;
          break;
        }
      }
    }
    if (recentCross) score_macd3 = 5;
    else if (dif > dea && (dif - dea) / Math.abs(dea || 0.01) > 0.1) score_macd3 = 3;
  }
  scores.macd3 = { score: score_macd3, max: 5, name: '金叉', detail: score_macd3 === 5 ? '2日内金叉' : score_macd3 === 3 ? '强势金叉' : '无' };
  details.push(`金叉: ${score_macd3}/5`);

  // ── 三、KDJ 短线 (10 分) ──

  // 3.1 K 值 (5 分): 前提 K>D 否则0分。V_min=0, V_max=50, K>50得5分
  let score_kdj1 = 0;
  if (kVal != null && dVal != null && kVal > dVal) {
    if (kVal > 70) score_kdj1 = 5; // v2.3.0: K>70得5分
    else if (kVal > 50) score_kdj1 = 3 + linear(kVal, 50, 70, 2); // 50-70之间从3分线性到5分
    else score_kdj1 = linear(kVal, 0, 50, 3); // 0-50之间线性到3分
  }
  scores.kdj1 = { score: score_kdj1, max: 5, name: 'K值', detail: kVal != null ? kVal.toFixed(1) : 'N/A' };
  details.push(`KDJ-K: ${score_kdj1.toFixed(1)}/5`);

  // 3.2 J 值 (5 分): V_min=150, V_max=100（倒序）。J≤100得5分；J≥150得0分
  let score_kdj2 = 0;
  if (jVal != null) {
    score_kdj2 = linear(jVal, 150, 100, 5); // 反向：越大分越低
  }
  scores.kdj2 = { score: score_kdj2, max: 5, name: 'J值', detail: jVal != null ? jVal.toFixed(1) : 'N/A' };
  details.push(`KDJ-J: ${score_kdj2.toFixed(1)}/5`);

  // ── 四、成交量 (15 分) ──

  const calcAvgVol = (days) => {
    const vals = klines.slice(-days).map(k => k.volume).filter(v => v != null && v > 0);
    return vals.length > 0 ? vals.reduce((a,b) => a+b, 0) / vals.length : 0;
  };
  const vol5 = calcAvgVol(5);
  const vol10 = calcAvgVol(10);

  // 4.1 量比 MA5 (7 分): V_min=1.0, V_max=1.4
  let score_vol1 = 0;
  if (v > 0 && vol5 > 0) {
    const ratio = v / vol5;
    score_vol1 = linear(ratio, 1.0, 2.5, 7); // v2.3.0: 满分阈值从1.4倍改为2.5倍
  }
  scores.vol1 = { score: score_vol1, max: 7, name: '量比MA5', detail: vol5 > 0 ? `${(v/vol5).toFixed(2)}x` : 'N/A' };
  details.push(`量/MA5: ${score_vol1.toFixed(1)}/7`);

  // 4.2 量比 MA10 (6 分): V_min=1.0, V_max=1.3
  let score_vol2 = 0;
  if (v > 0 && vol10 > 0) {
    const ratio = v / vol10;
    score_vol2 = linear(ratio, 1.0, 2.0, 6); // v2.3.0: 满分阈值从1.3倍改为2.0倍
  }
  scores.vol2 = { score: score_vol2, max: 6, name: '量比MA10', detail: vol10 > 0 ? `${(v/vol10).toFixed(2)}x` : 'N/A' };
  details.push(`量/MA10: ${score_vol2.toFixed(1)}/6`);

  // 4.3 量能增长率 (2 分): V_min=0%, V_max=50%
  let score_vol3 = 0;
  if (klines.length >= 4) {
    const v3 = klines[klines.length-1]?.volume || 0;
    const v2 = klines[klines.length-2]?.volume || 0;
    const v1 = klines[klines.length-3]?.volume || 0;
    // 增长率 = (当日-前日)/前日 × 100
    const growthRate = v2 > 0 ? ((v3 - v2) / v2) * 100 : 0;
    score_vol3 = linear(growthRate, 0, 50, 2);
  }
  scores.vol3 = { score: score_vol3, max: 2, name: '量能增长率', detail: klines.length>=4 ? `${((klines[klines.length-1]?.volume||0)/(klines[klines.length-2]?.volume||1)-1).toFixed(1)}%` : 'N/A' };
  details.push(`量增长: ${score_vol3.toFixed(1)}/2`);

  // ── 五、K 线形态 (12 分) ──

  // 5.1 突破幅度 (5 分): V_min=0%, V_max=8% (v2.3.0: 从3%改为8%)
  let score_kline1 = 0;
  if (klines.length >= 15) { // v2.3.0: 改为10日周期
    const recentHigh10 = Math.max(...klines.slice(-10).map(k => k.high).filter(v => v != null));
    const breakPct = ((c - recentHigh10) / recentHigh10) * 100;
    score_kline1 = linear(breakPct, 0, 8, 5); // v2.3.0: 满分阈值从3%改为8%
  }
  scores.kline1 = { score: score_kline1, max: 5, name: '突破幅度(10日)', detail: klines.length>=15 ? `${((c-Math.max(...klines.slice(-10).map(k=>k.high).filter(v=>v!=null)))/Math.max(...klines.slice(-10).map(k=>k.high).filter(v=>v!=null))*100).toFixed(2)}%` : 'N/A' }; // v2.3.0
  details.push(`突破: ${score_kline1.toFixed(1)}/5`);

  // 5.2 涨幅 (4 分): 3%-7%线性到4分；7%-10%保持3分；一字涨停0分 (v2.3.0)
  let score_kline2 = 0;
  if (chgPct >= 3 && chgPct <= 10) {
    if (Math.abs(chgPct - 10) < 0.5 && Math.abs(o - c) < 0.01) {
      // 一字涨停，0分
      score_kline2 = 0;
    } else if (chgPct >= 3 && chgPct <= 7) {
      score_kline2 = linear(chgPct, 3, 7, 4);
    } else if (chgPct > 7 && chgPct <= 10) {
      // 7%-10% 保持3分（自然涨停优于一字涨停）
      score_kline2 = 3;
    }
  }
  scores.kline2 = { score: score_kline2, max: 4, name: '涨幅', detail: `${chgPct.toFixed(2)}%` };
  details.push(`涨幅: ${score_kline2.toFixed(1)}/4`);

  // 5.3 上影线率 (3 分): V_min=1.0, V_max=0（倒序）, 公式=(1.0-上影线率)×3
  let score_kline3 = 0;
  if (h && l && c && o) {
    const body = Math.abs(c - o);
    const upperShadow = h - Math.max(c, o);
    if (body > 0) {
      const shadowRatio = upperShadow / body;
      score_kline3 = linear(shadowRatio, 1.0, 0, 3); // 反向：上影线率越小分越高
    }
  }
  scores.kline3 = { score: score_kline3, max: 3, name: '上影线率', detail: 'N/A' };
  details.push(`上影线: ${score_kline3.toFixed(1)}/3`);

  // ── 六、板块热点 (13 分) ──
  // 板块排名%(4分): V_min=20%, V_max=5%, 公式=(20%-排名%)/15%×4
  // 涨停股数(4分): V_min=0只, V_max=5只
  // 个股板块排名%(5分): V_min=50%, V_max=10%, 公式=(50%-排名%)/40%×5
  let score_sector1 = 0, score_sector2 = 0, score_sector3 = 0;
  if (sectorInfo) {
    const si = sectorInfo;
    if (si.sectorRankPercent != null) {
      score_sector1 = linear(si.sectorRankPercent, 20, 5, 4);
    }
    if (si.sectorLimitUpCount != null) {
      score_sector2 = linear(si.sectorLimitUpCount, 0, 5, 4);
    }
    if (si.stockRankPercent != null) {
      score_sector3 = linear(si.stockRankPercent, 50, 10, 5);
    }
  }
  scores.sector1 = { score: score_sector1, max: 4, name: '板块排名%', detail: sectorInfo ? `${(sectorInfo.sectorRankPercent??0).toFixed(1)}%(${sectorInfo.sectorChangePercent?.toFixed(1)}%)` : '数据缺失' };
  scores.sector2 = { score: score_sector2, max: 4, name: '板块涨停数', detail: sectorInfo ? `${sectorInfo.sectorLimitUpCount}只` : '数据缺失' };
  scores.sector3 = { score: score_sector3, max: 5, name: '个股板块排名', detail: sectorInfo ? `${(sectorInfo.stockRankPercent??0).toFixed(1)}%` : '数据缺失' };
  details.push(`板块: ${(score_sector1+score_sector2+score_sector3).toFixed(1)}/13`);

  // ── 七、资金流向 (7 分) ──
  // 主力净流入%(4分): V_min=0%, V_max=15%
  // 大单净流入%(3分): V_min=5%, V_max=15%, 公式=(占比-5%)/10%×3
  let score_flow1 = 0, score_flow2 = 0;
  if (flowInfo) {
    if (flowInfo.mainForcePercent != null) {
      score_flow1 = linear(flowInfo.mainForcePercent, 0, 15, 4);
    }
    if (flowInfo.largeOrderPercent != null) {
      score_flow2 = linear(flowInfo.largeOrderPercent, 2, 15, 3); // v2.3.0: 零分阈值从5%改为2%
    }
  }
  scores.flow1 = { score: score_flow1, max: 4, name: '主力净流入%', detail: flowInfo ? `${flowInfo.mainForcePercent?.toFixed(2)}%` : '数据缺失' };
  scores.flow2 = { score: score_flow2, max: 3, name: '大单净流入%', detail: flowInfo ? `${flowInfo.largeOrderPercent?.toFixed(2)}%` : '数据缺失' };
  details.push(`资金流: ${(score_flow1+score_flow2).toFixed(1)}/7`);

  // ── 八、大盘情绪 (15 分) ──
  // 上证涨幅(5分): V_min=-1%, V_max=1%, formula=(涨幅+1%)/2%×5。未站稳MA5最高3分。
  // 涨跌比(5分): V_min=0.8, V_max=2.0
  // 涨停溢价(5分): V_min=-2%, V_max=3%
  let score_mkt1 = 0, score_mkt2 = 0, score_mkt3 = 0;
  if (marketInfo) {
    if (marketInfo.sseChangePercent != null) {
      score_mkt1 = linear(marketInfo.sseChangePercent, -1, 0.5, 5); // v2.3.0: 满分阈值从1%改为0.5%
    }
    if (marketInfo.advDeclRatio != null) {
      score_mkt2 = linear(marketInfo.advDeclRatio, 0.8, 2.0, 5);
    }
    if (marketInfo.limitUpPremium != null) {
      score_mkt3 = linear(marketInfo.limitUpPremium, -2, 1.5, 5); // v2.3.0: 满分阈值从3%改为1.5%
    }
  }
  scores.mkt1 = { score: score_mkt1, max: 5, name: '上证涨幅', detail: marketInfo ? `${marketInfo.sseChangePercent.toFixed(2)}%` : '数据缺失' };
  scores.mkt2 = { score: score_mkt2, max: 5, name: '涨跌比', detail: marketInfo ? `${marketInfo.advDeclRatio.toFixed(2)}` : '数据缺失' };
  scores.mkt3 = { score: score_mkt3, max: 5, name: '涨停溢价', detail: marketInfo ? `${marketInfo.limitUpPremium.toFixed(2)}%` : '数据缺失' };
  details.push(`大盘: ${(score_mkt1+score_mkt2+score_mkt3).toFixed(1)}/15`);

  // 汇总基础分（四舍五入为整数）
  const baseScore = Math.round(score_ma1 + score_ma2 + score_ma3 +
    score_macd1 + score_macd2 + score_macd3 +
    score_kdj1 + score_kdj2 +
    score_vol1 + score_vol2 + score_vol3 +
    score_kline1 + score_kline2 + score_kline3 +
    score_sector1 + score_sector2 + score_sector3 +
    score_flow1 + score_flow2 +
    score_mkt1 + score_mkt2 + score_mkt3);

  return { baseScore, scores, details };
}

// ── 加分项计算 (最高 27 分) ──

function calcBonus(klines, stock, todaySSE, sectorInfo, policyConfig, stockDetail) {
  let bonusTotal = 0;
  let bonusItems = [];

  // ── 大盘超跌 (最高 10 分) — 同类就高不就低，不重复累加 ──
  let marketBonus = 0;
  let marketDetail = `上证${todaySSE.toFixed(2)}%`;
  if (todaySSE <= -3) {
    marketBonus = 5; // 当日暴跌>=3%，严重超跌
  } else if (todaySSE <= -2) {
    marketBonus = 3; // 当日跌幅>=2%
  } else if (todaySSE <= -1) {
    marketBonus = 2; // 当日跌幅>=1%
  }
  // TODO: 连续2日/3日跌>=2%的+6/+10分，需要接入历史大盘数据

  if (marketBonus > 0) {
    bonusItems.push({ name: '大盘超跌', score: marketBonus, detail: `上证${todaySSE.toFixed(2)}%` });
    bonusTotal += marketBonus;
  }

  // ── 板块超跌 (最高 10 分) ──
  if (sectorInfo?.sectorChangePercent != null && sectorInfo.sectorChangePercent <= -2) {
    let sectorBonus = 2; // 当日跌幅>=2%
    if (sectorInfo.sectorChangePercent <= -5) sectorBonus = 5; // v2.3.0: 跌幅>=5%，严重超跌
    else if (sectorInfo.sectorChangePercent <= -3.5) sectorBonus = 3; // v2.3.0: 跌幅>=3.5%
    bonusItems.push({ name: '板块超跌', score: sectorBonus, detail: `板块${sectorInfo.sectorChangePercent.toFixed(2)}%` });
    bonusTotal += sectorBonus;
  }

  // ── 压力消化 (最高 5 分) ──
  // 简化：检查近期是否有放量突破压力位的迹象
  let pressureBonus = 0;
  let breakCount = 0;
  if (klines.length >= 25) {
    const recent25 = klines.slice(-25);
    for (const k of recent25) {
      const chg = k.changePercent || 0;
      const vol = k.volume || 0;
      const avgVol = recent25.map(x => x.volume).filter(v => v != null && v > 0).reduce((a,b) => a+b, 0) / 25;
  // 压力消化：成交量>MA5均量（规范要求，取消1.2倍系数）
      if (chg > 2 && vol > avgVol) breakCount++;
    }
    if (breakCount >= 3) pressureBonus = 5;
    else if (breakCount >= 1) pressureBonus = 2;
  }
  if (pressureBonus > 0) {
    bonusItems.push({ name: '压力消化', score: pressureBonus, detail: `近25日${breakCount}次放量突破` });
    bonusTotal += pressureBonus;
  }

  // ── 确定性加分 (最高 15 分) — 按行业/题材命中强弱差异化计算 ──
  const certaintyState = calcCertaintyBonus(policyConfig, stockDetail, stock?.industry);
  const certaintyBonus = certaintyState.score;
  if (certaintyBonus > 0) {
    bonusItems.push({ name: '确定性加分', score: certaintyBonus, detail: certaintyState.detail });
    bonusTotal += certaintyBonus;
  }

  // v2.3.0: 加分项总上限15分
  bonusTotal = round1(Math.min(bonusTotal, 15));
  return { bonusTotal, bonusItems };
}

// ── 扣分项计算 (非奸即盗) ──

function calcDeductions(stock, klines, marketInfo, sectorInfo) {
  const latest = klines[klines.length - 1];
  const prev = klines.length >= 2 ? klines[klines.length - 2] : latest;
  const c = latest.close;
  const o = latest.open;
  const h = latest.high;
  const l = latest.low;
  const v = latest.volume || 0;
  const chgPct = latest.changePercent || 0;
  const turnover = latest.turnoverRate || 0;
  const floatMV = stock.floatMarketValue || 0;
  const todaySSE = marketInfo?.sseChangePercent ?? 0;

  // 计算均量
  const calcAvgVol = (days) => {
    const vals = klines.slice(-days).map(k => k.volume).filter(v => v != null && v > 0);
    return vals.length > 0 ? vals.reduce((a,b) => a+b, 0) / vals.length : 0;
  };
  const vol5 = calcAvgVol(5);

  let deductions = [];
  let totalDed = 0;

  // 1. 尾盘急拉 (-5) — 需要分时数据(14:30后拉升)，暂不实现
  // 2. 高位放量滞涨 (-5)
  if (chgPct < 3 && v > 0 && vol5 > 0 && v > vol5 * 2.5) {
    deductions.push({ name: '高位放量滞涨', score: -5, detail: `涨幅${chgPct.toFixed(2)}%,量${(v/vol5).toFixed(2)}x` });
    totalDed += 5;
  }

  // 3. 长上影线 (-3)
  if (h && l && c && o) {
    const upperShadow = h - Math.max(c, o);
    const body = Math.abs(c - o);
    const shadowPct = (h - Math.max(c, o)) / c * 100;
    if (body > 0 && upperShadow > body * 2 && shadowPct > 3) {
      deductions.push({ name: '长上影线', score: -3, detail: `上影线${shadowPct.toFixed(1)}%` });
      totalDed += 3;
    }
  }

  // 4. 巨量阴线 (-6)
  if (c < o && v > 0 && vol5 > 0 && v > vol5 * 2 && Math.abs(chgPct) > 3) {
    deductions.push({ name: '巨量阴线', score: -6, detail: `跌幅${chgPct.toFixed(2)}%,量${(v/vol5).toFixed(2)}x` });
    totalDed += 6;
  }

  // 9. 换手率异常 (-3)
  if (floatMV > 0) {
    const floatMVYi = floatMV / 1e8;
    if (floatMVYi < 50 && turnover > 20) {
      deductions.push({ name: '换手率异常(小盘)', score: -3, detail: `换手${turnover.toFixed(1)}%` });
      totalDed += 3;
    } else if (floatMVYi >= 50 && turnover > 15) {
      deductions.push({ name: '换手率异常(大盘)', score: -3, detail: `换手${turnover.toFixed(1)}%` });
      totalDed += 3;
    }
  }

  // 14. 连续缩量涨停后突然爆量 (-4)
  if (klines.length >= 5) {
    const last5 = klines.slice(-5);
    let consecutiveLimitUp = true;
    for (let i = 1; i <= 3; i++) {
      const k = last5[last5.length - 1 - i];
      if (!k || Math.abs((k.changePercent || 0) - 10) > 1) { consecutiveLimitUp = false; break; }
    }
    if (consecutiveLimitUp && last5.length >= 2) {
      const prevVol = last5[last5.length - 2]?.volume || 0;
      if (prevVol > 0 && v > prevVol * 5) {
        deductions.push({ name: '缩量涨停后爆量', score: -4, detail: `量${(v/prevVol).toFixed(1)}x前日` });
        totalDed += 4;
      }
    }
  }

  // 7. 利好兑现高开低走 (-4) — 当日收阴且开盘价>收盘价
  if (c < o && o > (prev.close || c) * 1.01) {
    const openChg = (o - prev.close) / prev.close * 100;
    const entityPct = Math.abs(c - o) / o * 100;
    if (openChg > 1 && entityPct > 2) {
      deductions.push({ name: '利好兑现高开低走', score: -4, detail: `高开${openChg.toFixed(1)}%,实体${entityPct.toFixed(1)}%` });
      totalDed += 4;
    }
  }

  // 13. 逆势独木难支 (-3) — 大盘跌幅>2%时，个股独自涨停
  if (chgPct >= 9.5 && todaySSE <= -2) {
    deductions.push({ name: '逆势独木难支', score: -3, detail: `大盘${todaySSE.toFixed(2)}%,个股涨停` });
    totalDed += 3;
  }
  // 板块共振版本：大盘跌>2%且板块跌>3%
  if (chgPct >= 9.5 && todaySSE <= -2 && sectorInfo?.sectorChangePercent != null && sectorInfo.sectorChangePercent <= -3) {
    deductions.push({ name: '逆势独木难支(板块共振)', score: -3, detail: `大盘${todaySSE.toFixed(2)}%,板块${sectorInfo.sectorChangePercent.toFixed(2)}%` });
    totalDed += 3;
  }

  // 汇总（扣至0为止）
  return { totalDed: Math.min(totalDed, 100), deductions };
}

// ── 主流程 ──

async function main() {
  console.log(`
╔══════════════════════════════════════════════════╗
║     超短线量化选股助手 v${SCRIPT_VERSION}  联网增强版          ║
║     总资金：${String(TOTAL_FUNDS).padStart(8)} 元                    ║
║     交易标的：沪/深主板 + 创业板                 ║
╚══════════════════════════════════════════════════╝
`);

  // 自动更新检查（月初/月中）
  await checkUpdate(true);

  const startTime = Date.now();

  console.log('📡 获取加分配置...');
  const policyState = fetchPolicyScoreConfig();
  const policyConfig = policyState.config;
  if (policyConfig) {
    const policyVersion = policyConfig.version || '未标注版本';
    const policyDate = policyConfig.updated_at || '未标注日期';
    if (policyState.source === 'gist') {
      console.log(`  ✅ 已加载 Gist 加分配置: ${policyVersion} (${policyDate})`);
    } else if (policyState.source === 'legacy-gist') {
      console.log(`  ⚠️ Gist 当前仍是旧结构，已从兼容地址读取加分配置: ${policyVersion} (${policyDate})`);
    } else {
      console.log(`  ⚠️ Gist 加分配置获取失败，改用本地缓存: ${policyVersion} (${policyDate})`);
    }
  } else {
    console.log('  ⚠️ 未找到可用加分配置，确定性加分按 0 分处理');
  }

  // ── 从东方财富 API 获取实时数据（替代硬编码和缺失数据）──

  // 1. 获取大盘数据 + 涨停溢价（并行）
  console.log('📡 获取大盘数据...');
  const [marketRaw, premiumRaw] = await Promise.all([
    getMarketData(),
    getZTPremium(),
  ]);
  const marketInfo = marketRaw ? {
    sseChangePercent: marketRaw.sseChangePercent,
    advDeclRatio: marketRaw.advDeclRatio,
    limitUpPremium: premiumRaw,
  } : null;
  const todaySSE = marketRaw ? marketRaw.sseChangePercent : -2.26;

  if (marketInfo) {
    console.log(`  ✅ 上证 ${marketRaw.price} ${marketRaw.sseChangePercent >= 0 ? '+' : ''}${marketRaw.sseChangePercent.toFixed(2)}% 涨:${marketRaw.riseCount} 跌:${marketRaw.fallCount} 溢价:${(premiumRaw ?? 0).toFixed(2)}%`);
  } else {
    console.log(`  ⚠️ 大盘数据获取失败，使用默认值`);
  }

  // Step 1: 获取候选股
  const { candidates, yesterdayPool } = await getCandidates();
  if (candidates.length === 0) {
    console.log('\n❌ 没有找到候选股，请检查网络或稍后重试');
    return;
  }

  // 截取前 MAX_CANDIDATES 只
  const toAnalyze = candidates.slice(0, MAX_CANDIDATES);

  console.log('📡 获取个股详情...');
  const stockDetailMap = await buildStockDetailMap(toAnalyze);
  console.log(`  ✅ 已获取 ${Object.keys(stockDetailMap).length} 只股票的详情信息`);

  // 2. 获取板块热点数据（批量一次性获取）
  console.log('📡 获取板块数据...');
  const sectorInfoMap = await buildSectorInfo(toAnalyze, stockDetailMap);
  console.log(`  ✅ 已获取 ${sectorInfoMap ? Object.keys(sectorInfoMap).length : 0} 只股票的板块信息`);

  console.log(`\n🔎 详细分析 ${toAnalyze.length} 只候选股...\n`);

  const results = [];

  for (let i = 0; i < toAnalyze.length; i++) {
    const stock = toAnalyze[i];
    const code = stock.code;
    const name = stock.name;

    process.stdout.write(`  [${i+1}/${toAnalyze.length}] 🔍 ${code} ${name} ... `);

    // 获取技术指标 K 线
    const klines = await getIndicators(code);
    if (!klines || klines.length < 60) {
      console.log('⚠️ K线数据不足');
      continue;
    }

    // 获取行情
    const quote = await getQuote(code);

    // 硬门槛检查
    const hardFilter = checkHardFilters(stock, klines);
    if (!hardFilter.pass) {
      console.log(`❌ ${hardFilter.reason}`);
      continue;
    }

    // 计算基础分（传入板块、概念、大盘、资金流数据）
    const sectorInfo = sectorInfoMap ? sectorInfoMap[code] : null;
    const stockDetail = stockDetailMap[code] || await getStockDetail(code);
    const flowInfo = stockDetail ? {
      mainForcePercent: stockDetail.mainForcePercent,
      largeOrderPercent: stockDetail.largeOrderPercent,
    } : null;
    const { baseScore, scores, details } = calcBaseScore(stock, klines, quote, sectorInfo, null, marketInfo, flowInfo);

    // 计算加分项
    const { bonusTotal, bonusItems } = calcBonus(klines, stock, todaySSE, sectorInfo, policyConfig, stockDetail);

    // 计算扣分项
    let { totalDed, deductions } = calcDeductions(stock, klines, marketInfo, sectorInfo);

    // 新增盘后扣分项（异步爬取，不阻塞主流程）
    const newDeductions = await Promise.all([
      checkLimitUpBreak(stock, klines),
      checkFailedLimitUp(stock, klines),
      checkDragonTigerRetail(code),
      checkDoubleTop(stock, klines),
      checkAnnouncementRisk(code)
    ]);
    for (const d of newDeductions) {
      if (d) { deductions.push(d); totalDed += Math.abs(d.score); }
    }

    // 总分（四舍五入为整数）
    const finalScore = Math.round(Math.max(0, baseScore + bonusTotal - totalDed));
    const effectiveDed = Math.min(totalDed, baseScore + bonusTotal); // 扣至0为止

    // 等级只看总分：A(>=75) / B(68-74) / C(60-67) / D(<60)
    const { level, suggestion } = determineLevelAndSuggestion(finalScore);

    console.log(`✅ 基础${baseScore}/100 +${bonusTotal} -${effectiveDed} = ${finalScore}分 [${level}]`);

    results.push({
      code, name,
      price: stock.price || quote?.price || (klines[klines.length-1]?.close) || 0,
      changePercent: stock.changePercent ?? (klines[klines.length-1]?.changePercent) ?? 0,
      industry: stock.industry || '',
      continuousBoard: stock.continuousBoardCount || 0,
      turnoverRate: stock.turnoverRate,
      baseScore: Math.round(baseScore),
      bonusTotal: Math.round(bonusTotal),
      deductionTotal: Math.round(effectiveDed),
      finalScore,
      level,
      suggestion,
      details: details.join(' | '),
      bonusItems,
      deductions,
      scores,
      klineLatest: klines[klines.length - 1],
      vol5: (() => {
        const vals = klines.slice(-5).map(k => k.volume).filter(v => v != null && v > 0);
        return vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
      })() // v2.3.0: 新增量比MA5原始数据，供HTML显示
    });

    // 避免请求过快
    if (i < toAnalyze.length - 1) await sleep(500); // v2.3.0: 从200ms改为500ms防反爬
  }

  // 排序：按最终得分降序
  results.sort((a, b) => b.finalScore - a.finalScore);

  // 输出前十
  const top10 = results.slice(0, 10);

  console.log(`\n${'='.repeat(60)}`);
  console.log(`  📋 选股结果（前${top10.length}名）`);
  console.log(`${'='.repeat(60)}\n`);

  for (let i = 0; i < top10.length; i++) {
    const r = top10[i];
    console.log(`  ${'─'.repeat(56)}`);
    console.log(`  #${i+1} 【${r.code}】${r.name}`);
    console.log(`     行业: ${r.industry}  连板: ${r.continuousBoard}  换手: ${r.turnoverRate?.toFixed(2)}%`);
    console.log(`     基础分: ${r.baseScore}/100  +${r.bonusTotal}  -${r.deductionTotal}  = ${r.finalScore}分 [${r.level}]`);
    console.log(`     建议: ${r.suggestion}`);
    if (r.bonusItems.length > 0) {
      console.log(`     加分: ${r.bonusItems.map(b => `${b.name}+${b.score}`).join(' ')}`);
    }
    if (r.deductions.length > 0) {
      console.log(`     扣分: ${r.deductions.map(d => `${d.name}${d.score}`).join(' ')}`);
    }
    console.log(`     详情: ${r.details}`);
  }

  // 生成 HTML 报告
  generateHTML(top10, results, startTime);

  console.log(`\n${'='.repeat(60)}`);
  console.log(`  ✅ 选股完成！耗时 ${((Date.now() - startTime)/1000).toFixed(1)}s`);
  console.log(`  📄 报告已生成：${path.resolve(OUTPUT_FILE)}`);
  console.log(`${'='.repeat(60)}\n`);
}

// ── HTML 报告生成 ──

function generateHTML(top10, allResults, startTime) {
  const now = new Date();
  const dateStr = formatDate(now);
  const timeStr = now.toLocaleTimeString('zh-CN');

  const rows = top10.map((r, i) => {
    const bonusStr = r.bonusItems.map(b => `<span class="bonus">${b.name}+${b.score}</span>`).join(' ');
    const dedStr = r.deductions.map(d => `<span class="deduction">${d.name}${d.score}</span>`).join(' ');
    const levelColor = r.level === 'A' ? '#00c853' : r.level === 'B' ? '#ffd600' : r.level === 'C' ? '#ff9100' : '#ff1744';

    return `
    <tr>
      <td>${i+1}</td>
      <td class="code">${r.code}</td>
      <td class="name">${r.name}</td>
      <td>${r.industry}</td>
      <td>${r.continuousBoard}</td>
      <td>${r.turnoverRate?.toFixed(1)}%</td>
      <td class="num">${r.changePercent?.toFixed(2)}%</td>
      <td class="num">${r.vol5 > 0 ? (r.klineLatest?.volume / r.vol5).toFixed(2) + 'x' : 'N/A'}</td>
      <td class="num">${r.baseScore}</td>
      <td class="num">+${r.bonusTotal}</td>
      <td class="num">-${r.deductionTotal}</td>
      <td class="num" style="color:${levelColor};font-weight:bold">${r.finalScore}</td>
      <td><span class="level level-${r.level}">${r.level}</span></td>
      <td style="font-size:12px">${r.suggestion}</td>
      <td style="font-size:11px;max-width:200px">${r.details} ${bonusStr} ${dedStr}</td>
    </tr>`;
  }).join('\n');

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>超短线量化选股结果</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:-apple-system,'Microsoft YaHei',sans-serif; background:#0d1117; color:#c9d1d9; padding:20px; }
  .header { text-align:center; padding:30px 0; border-bottom:1px solid #30363d; margin-bottom:20px; }
  .header h1 { font-size:24px; color:#58a6ff; margin-bottom:8px; }
  .header .meta { color:#8b949e; font-size:14px; }
  .summary { display:flex; gap:15px; justify-content:center; margin-bottom:20px; flex-wrap:wrap; }
  .summary-item { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:15px 25px; text-align:center; min-width:120px; }
  .summary-item .num { font-size:28px; font-weight:bold; color:#58a6ff; }
  .summary-item .label { font-size:12px; color:#8b949e; margin-top:4px; }
  table { width:100%; border-collapse:collapse; background:#161b22; border-radius:8px; overflow:hidden; }
  th { background:#21262d; color:#8b949e; padding:10px 8px; font-size:12px; text-align:left; white-space:nowrap; }
  td { padding:8px; border-top:1px solid #30363d; font-size:13px; }
  tr:hover { background:#1c2128; }
  .code { font-family:monospace; color:#58a6ff; }
  .name { font-weight:bold; }
  .num { text-align:center; font-family:monospace; }
  .level { display:inline-block; padding:2px 8px; border-radius:4px; font-weight:bold; font-size:12px; }
  .level-A { background:#003d1a; color:#00c853; }
  .level-B { background:#3d2e00; color:#ffd600; }
  .level-C { background:#3d1c00; color:#ff9100; }
  .level-D { background:#3d0000; color:#ff1744; }
  .bonus { color:#00c853; font-size:11px; margin-right:4px; }
  .deduction { color:#ff1744; font-size:11px; margin-right:4px; }
  .footer { text-align:center; padding:20px; color:#8b949e; font-size:12px; }
</style>
</head>
<body>
<div class="header">
  <h1>📊 超短线量化选股结果</h1>
  <div class="meta">生成时间：${dateStr} ${timeStr} | 总资金：7万元 | 标的：沪/深主板 + 创业板</div>
</div>
<div class="summary">
  <div class="summary-item"><div class="num">${top10.length}</div><div class="label">输出个股</div></div>
  <div class="summary-item"><div class="num">${allResults.length}</div><div class="label">通过筛选</div></div>
  <div class="summary-item"><div class="num">${allResults.filter(r => r.level === 'A').length}</div><div class="label">A级出手</div></div>
  <div class="summary-item"><div class="num">${allResults.filter(r => r.level === 'B').length}</div><div class="label">B级试错</div></div>
  <div class="summary-item"><div class="num">${allResults.filter(r => r.level === 'C').length}</div><div class="label">C级观察</div></div>
</div>
<table>
<thead>
<tr>
  <th>#</th><th>代码</th><th>名称</th><th>行业</th><th>连板</th><th>换手</th><th>今日涨幅</th><th>量比MA5</th>
  <th>基础</th><th>加分</th><th>扣分</th><th>总分</th><th>等级</th><th>建议</th><th>明细</th>
</tr>
</thead>
<tbody>
${rows}
</tbody>
</table>
<div class="footer">
  ⚠️ 本结果仅供参考，不构成投资建议。股市有风险，投资需谨慎。<br>
  💡 A级(≥75)可出手 | B级(68-74)轻仓试错 | C级(60-67)观察名单 | D级(<60)放弃
</div>
</body>
</html>`;

  fs.writeFileSync(OUTPUT_FILE, html, 'utf-8');
}

// ── 启动 ──

if (require.main === module) {
  main().catch(err => {
    console.error('\n❌ 选股出错:', err.message);
    process.exit(1);
  });
}

module.exports = {
  determineLevelAndSuggestion,
};
