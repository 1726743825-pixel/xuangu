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
 * 依赖：
 *   npx stock-sdk (自动安装)
 * ============================================================
 */
'use strict';

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

// ── 配置 ──
const TOTAL_FUNDS = 70000;               // 总资金 7 万元
const OUTPUT_FILE = 'D:/Program Files/xuangu/result/选股结果.html';
const MAX_CANDIDATES = 60;               // 最多详细分析的候选股
const KLINE_LIMIT = 150;                 // 获取 K 线天数（确保 MA60 有效）
const SDK_TIMEOUT = 30000;               // 每个 CLI 调用超时(ms)
const SDK_BIN = `npx -y stock-sdk`;      // CLI 命令

// ── 自动更新配置 ──
const SCRIPT_VERSION = "2.2.0";          // 当前版本号（每月初/中更新Gist时递增）
const UPDATE_URL = "https://gist.githubusercontent.com/1726743825-pixel/be9bfb4c401fbe9a6d10e56b344c2875/raw/stock_screener.js";
const AUTO_UPDATE_CHECK = true;          // 启用自动更新检查
// 检查日期：每月1-3日 和 15-17日（月初+月中）
const UPDATE_CHECK_DAYS = [[1,2,3], [15,16,17]];

// ── 确定性加分配置（从 GitHub Gist 获取） ──
const POLICY_SCORE_URL = "https://gist.githubusercontent.com/1726743825-pixel/be9bfb4c401fbe9a6d10e56b344c2875/raw/policy_scores.json";
// 上述 URL 指向 GitHub Gist，其中应存放 JSON 格式的确定性加分配置，格式见 fetchPolicyScores()
// 每月初更新 Gist 中的 value 值即可，无需改动脚本

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

// ── 自动更新检查（整脚本替换，用于Gist全量更新） ──

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
  if (!shouldCheckUpdate()) {
    if (!silent) console.log('  ℹ️  不在更新检查日（1-3日/15-17日），跳过自动更新');
    return;
  }

  try {
    const remote = execSync(
      `curl -sL --max-time 10 "${UPDATE_URL}"`,
      { timeout: 15000, encoding: 'utf-8', stdio: ['pipe','pipe','pipe'] }
    ).trim();
    // 从远程脚本中提取版本号
    const m = remote.match(/const SCRIPT_VERSION\s*=\s*['"]([^'"]+)['"]/);
    if (!m) { if (!silent) console.log('  ⚠️  远程脚本版本格式异常'); return; }

    const remoteVer = m[1];
    if (remoteVer !== SCRIPT_VERSION) {
      console.log(`  📥 发现新版本 ${remoteVer} (当前 ${SCRIPT_VERSION})，正在更新...`);
      // 备份当前脚本
      const selfPath = process.argv[1] || __filename;
      fs.writeFileSync(selfPath + '.bak', fs.readFileSync(selfPath), 'utf-8');
      // 写回新版本
      fs.writeFileSync(selfPath, remote, 'utf-8');
      console.log(`  ✅ 已更新至 ${remoteVer}，旧版备份至 ${path.basename(selfPath)}.bak`);
      console.log(`  🔄 请重新运行脚本以使用新版本`);
      process.exit(0);
    } else {
      if (!silent) console.log(`  ✅ 已是最新版本 ${SCRIPT_VERSION}`);
    }
  } catch (e) {
    if (!silent) console.log(`  ⚠️  检查更新失败: ${e.message.slice(0, 60)}`);
  }
}

// ── 从 GitHub Gist 获取确定性加分配置（JSON） ──

function fetchPolicyScores() {
  try {
    const curlCmd = 'curl -sL --max-time 10 "' + POLICY_SCORE_URL + '"';
    const raw = execSync(curlCmd,
      { timeout: 15000, encoding: "utf-8", stdio: ["pipe","pipe","pipe"] }
    ).trim();
    let config;
    try { config = JSON.parse(raw); } catch { return null; }
    if (!config || !config.version || !Array.isArray(config.scores)) return null;
    console.log("  📥 已获取确定性加分配置 (" + config.version + ")");
    return config.scores;
  } catch (e) {
    return null;
  }
}

// ── 数据获取 ──

/** 获取涨停/强势股池 */
async function getCandidates() {
  console.log('📡 获取涨停股池...');
  // 涨停股池
  let pool = runJSON(`${SDK_BIN} ztpool zt -q`, 30000) || [];
  // 强势股池
  const strongPool = runJSON(`${SDK_BIN} ztpool strong -q`, 30000) || [];
  // 昨日涨停
  const yesterdayPool = runJSON(`${SDK_BIN} ztpool yesterday -q`, 30000) || [];

  // 合并去重
  const seen = new Set();
  const all = [...pool, ...strongPool, ...yesterdayPool];
  const merged = [];
  for (const s of all) {
    if (s && s.code && !seen.has(s.code) && isAllowed(s.code, s.name)) {
      seen.add(s.code);
      merged.push(s);
    }
  }
  console.log(`  ✅ 候选池：涨停 ${pool.length} + 强势 ${strongPool.length} + 昨涨 ${yesterdayPool.length}`);
  console.log(`  ✅ 去重+过滤后：${merged.length} 只候选股票`);
  return merged;
}

/** 获取个股技术指标 K 线 — 带 Sina 备用源 */
function getIndicators(code) {
  // 首选：stock-sdk indicators
  const data = runJSON(
    `${SDK_BIN} indicators ${code} --ma 5,10,20,60 --macd --kdj --limit ${KLINE_LIMIT} -q -f json`,
    30000
  );
  if (data && data.length >= 60) return data;

  // 备用：Sina 日 K 线 API + 本地计算指标
  const prefix = code.startsWith('6') ? 'sh' : 'sz';
  const url = `https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20${prefix}${code}=/CN_MarketData.getKLineData?symbol=${prefix}${code}&scale=240&ma=no&datalen=1023`;
  try {
    const raw = run(`curl -sL --max-time 15 "${url}"`, 20000);
    if (!raw) return [];
    // 提取 JSON 部分: var xxx=([...]); 
    const m = raw.match(/\((\[[\s\S]*\])\)/);
    if (!m) return [];
    const bars = JSON.parse(m[1]);
    if (!bars || bars.length < 60) return [];

    // 转换格式并计算指标
    const klines = bars.map(b => ({
      date: b.day,
      open: parseFloat(b.open),
      close: parseFloat(b.close),
      high: parseFloat(b.high),
      low: parseFloat(b.low),
      volume: parseInt(b.volume) || 0,
      amount: 0,
      changePercent: 0,
      turnoverRate: 0,
      ma: {}, macd: {}, kdj: {}
    }));

    // 计算 changePercent
    for (let i = 1; i < klines.length; i++) {
      const prevClose = klines[i-1].close;
      klines[i].changePercent = prevClose > 0 ? ((klines[i].close - prevClose) / prevClose) * 100 : 0;
    }

    // 计算 MA
    const calcMA = (arr, period) => {
      const result = [];
      for (let i = 0; i < arr.length; i++) {
        if (i < period - 1) { result.push(null); continue; }
        let sum = 0;
        for (let j = i - period + 1; j <= i; j++) sum += arr[j];
        result.push(sum / period);
      }
      return result;
    };
    const closes = klines.map(k => k.close);
    const ma5Arr = calcMA(closes, 5);
    const ma10Arr = calcMA(closes, 10);
    const ma20Arr = calcMA(closes, 20);
    const ma60Arr = calcMA(closes, 60);
    for (let i = 0; i < klines.length; i++) {
      klines[i].ma = { ma5: ma5Arr[i], ma10: ma10Arr[i], ma20: ma20Arr[i], ma60: ma60Arr[i] };
    }

    // 计算 MACD (12, 26, 9)
    const ema = (arr, period) => {
      const result = []; const k = 2 / (period + 1);
      for (let i = 0; i < arr.length; i++) {
        if (i === 0) { result.push(arr[i]); continue; }
        result.push(arr[i] * k + result[i-1] * (1 - k));
      }
      return result;
    };
    const ema12 = ema(closes, 12);
    const ema26 = ema(closes, 26);
    const difArr = ema12.map((v, i) => v - ema26[i]);
    const deaArr = ema(difArr, 9);
    const macdArr = difArr.map((v, i) => (v - deaArr[i]) * 2);
    for (let i = 0; i < klines.length; i++) {
      klines[i].macd = { dif: difArr[i], dea: deaArr[i], macd: macdArr[i] };
    }

    // 计算 KDJ (9, 3, 3)
    const calcKDJ = () => {
      const kArr = [], dArr = [], jArr = [];
      let prevK = 50, prevD = 50;
      for (let i = 0; i < klines.length; i++) {
        const start = Math.max(0, i - 8);
        const hh = Math.max(...klines.slice(start, i+1).map(k => k.high));
        const ll = Math.min(...klines.slice(start, i+1).map(k => k.low));
        const rsv = (hh !== ll) ? ((klines[i].close - ll) / (hh - ll)) * 100 : 50;
        const kVal = (2/3) * prevK + (1/3) * rsv;
        const dVal = (2/3) * prevD + (1/3) * kVal;
        kArr.push(kVal); dArr.push(dVal); jArr.push(3 * kVal - 2 * dVal);
        prevK = kVal; prevD = dVal;
      }
      return { kArr, dArr, jArr };
    };
    const { kArr, dArr, jArr } = calcKDJ();
    for (let i = 0; i < klines.length; i++) {
      klines[i].kdj = { k: kArr[i], d: dArr[i], j: jArr[i] };
      // 补上 changePercent（用真实数据覆盖）
      if (i > 0 && closes[i-1] > 0) {
        klines[i].changePercent = ((closes[i] - closes[i-1]) / closes[i-1]) * 100;
      }
    }

    return klines;
  } catch {
    return [];
  }
}

/** 获取个股行情 */
function getQuote(code) {
  const data = runJSON(`${SDK_BIN} quote ${code} -q -f json`, 15000);
  return data ? data[0] : null;
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
  const high20 = klines.slice(-20).map(k => k.high).filter(v => v != null);
  if (high20.length >= 10) {
    const recentHigh = Math.max(...high20.slice(-5));
    const earlierHigh = Math.max(...high20.slice(0, 5));
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

function calcBaseScore(stock, klines, quote, sectorInfo, conceptInfo) {
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
    if (val == null) return 0;
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
    score_ma2 = linear(dev, 0, 2, 4);
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
    if (kVal > 50) score_kdj1 = 5;
    else score_kdj1 = linear(kVal, 0, 50, 5);
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
    score_vol1 = linear(ratio, 1.0, 1.4, 7);
  }
  scores.vol1 = { score: score_vol1, max: 7, name: '量比MA5', detail: vol5 > 0 ? `${(v/vol5).toFixed(2)}x` : 'N/A' };
  details.push(`量/MA5: ${score_vol1.toFixed(1)}/7`);

  // 4.2 量比 MA10 (6 分): V_min=1.0, V_max=1.3
  let score_vol2 = 0;
  if (v > 0 && vol10 > 0) {
    const ratio = v / vol10;
    score_vol2 = linear(ratio, 1.0, 1.3, 6);
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

  // 5.1 突破幅度 (5 分): V_min=0%, V_max=3%
  let score_kline1 = 0;
  if (klines.length >= 25) {
    const recentHigh20 = Math.max(...klines.slice(-20).map(k => k.high).filter(v => v != null));
    const breakPct = ((c - recentHigh20) / recentHigh20) * 100;
    score_kline1 = linear(breakPct, 0, 3, 5);
  }
  scores.kline1 = { score: score_kline1, max: 5, name: '突破幅度', detail: klines.length>=25 ? `${((c-Math.max(...klines.slice(-20).map(k=>k.high).filter(v=>v!=null)))/Math.max(...klines.slice(-20).map(k=>k.high).filter(v=>v!=null))*100).toFixed(2)}%` : 'N/A' };
  details.push(`突破: ${score_kline1.toFixed(1)}/5`);

  // 5.2 涨幅 (4 分): 3%-7%线性到4分；7%-9%线性降到2分；<3%或一字涨停0分
  let score_kline2 = 0;
  if (chgPct >= 3 && chgPct < 9 && Math.abs(chgPct - 10) > 0.5) { // 排除一字涨停
    if (chgPct >= 3 && chgPct <= 7) {
      score_kline2 = linear(chgPct, 3, 7, 4);
    } else {
      // 7%-9% 线性降到2分
      score_kline2 = linear(chgPct, 7, 9, 2); // 在7%时2分，9%时0分... 不对
      // 修正：7%时4分，9%时2分，线性下降
      // 从4分线性降到2分
      score_kline2 = 4 - linear(chgPct, 7, 9, 2);
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

  // ── 六、板块热点 (13 分) — 数据缺失按0分处理 ──
  // 线性公式已定义，数据可用时激活：
  // 板块排名%(4分): V_min=20%, V_max=5%, 公式=(20%-排名%)/15%×4
  // 涨停股数(4分): V_min=0只, V_max=5只
  // 个股板块排名%(5分): V_min=50%, V_max=10%, 公式=(50%-排名%)/40%×5
  let score_sector1 = 0, score_sector2 = 0, score_sector3 = 0;
  scores.sector1 = { score: 0, max: 4, name: '板块排名%', detail: '数据缺失(需MCP)' };
  scores.sector2 = { score: 0, max: 4, name: '板块涨停数', detail: '数据缺失(需MCP)' };
  scores.sector3 = { score: 0, max: 5, name: '个股板块排名', detail: '数据缺失(需MCP)' };
  details.push(`板块: 0/13 (数据缺失)`);

  // ── 七、资金流向 (7 分) — 数据缺失按0分处理 ──
  // 主力净流入%(4分): V_min=0%, V_max=15%
  // 大单净流入%(3分): V_min=5%, V_max=15%, 公式=(占比-5%)/10%×3
  let score_flow1 = 0, score_flow2 = 0;
  scores.flow1 = { score: 0, max: 4, name: '主力净流入%', detail: '数据缺失(需MCP)' };
  scores.flow2 = { score: 0, max: 3, name: '大单净流入%', detail: '数据缺失(需MCP)' };
  details.push(`资金流: 0/7 (数据缺失)`);

  // ── 八、大盘情绪 (15 分) — 使用 todaySSE（从 main 传入）──
  // 上证涨幅(5分): V_min=-1%, V_max=1%, formula=(涨幅+1%)/2%×5。未站稳MA5最高3分。
  // 涨跌比(5分): V_min=0.8, V_max=2.0
  // 涨停溢价(5分): V_min=-2%, V_max=3%
  let score_mkt1 = 0, score_mkt2 = 0, score_mkt3 = 0;
  // 注：大盘数据需从外部传入，这里暂用0分
  scores.mkt1 = { score: 0, max: 5, name: '上证涨幅', detail: '需传入todaySSE' };
  scores.mkt2 = { score: 0, max: 5, name: '涨跌比', detail: '数据缺失' };
  scores.mkt3 = { score: 0, max: 5, name: '涨停溢价', detail: '数据缺失' };
  details.push(`大盘: 0/15 (数据缺失)`);

  // 汇总基础分
  const baseScore = score_ma1 + score_ma2 + score_ma3 +
    score_macd1 + score_macd2 + score_macd3 +
    score_kdj1 + score_kdj2 +
    score_vol1 + score_vol2 + score_vol3 +
    score_kline1 + score_kline2 + score_kline3 +
    score_sector1 + score_sector2 + score_sector3 +
    score_flow1 + score_flow2 +
    score_mkt1 + score_mkt2 + score_mkt3;

  return { baseScore, scores, details };
}

// ── 加分项计算 (最高 27 分) ──

function calcBonus(klines, stock, todaySSE, remoteScores) {
  let bonusTotal = 0;
  let bonusItems = [];

  // ── 大盘超跌 (最高 10 分) — 同类就高不就低，不重复累加 ──
  let marketBonus = 0;
  if (todaySSE <= -2) {
    // 当日跌幅>=2% => +3分 (A4)
    // 连续2日跌幅>=2% => +6分 (A5) — 简化，只用当日数据
    // 连续3日跌幅>=2% => +10分 (A6)
    marketBonus = 3;
  } else if (todaySSE <= -1) {
    // 当日跌幅>=1% => +2分 (A1)
    marketBonus = 2;
  }

  if (marketBonus > 0) {
    bonusItems.push({ name: '大盘超跌', score: marketBonus, detail: `上证${todaySSE.toFixed(2)}%` });
    bonusTotal += marketBonus;
  }

  // ── 板块超跌 (最高 10 分) — 同类就高不就低，不重复累加 ──
  // 数据缺失，暂按0分处理（需通过 MCP 获取板块实时跌幅数据）
  // 如需激活，需获取个股所属板块的当日跌幅并对照以下规则：
  //   板块当日跌幅>=2% => +2分 (B1)
  //   连续2日跌幅>=2% => +4分 (B2)
  //   连续3日跌幅>=2% => +6分 (B3)
  //   板块当日跌幅>=3.5% => +2分 (B4)
  //   连续2日跌幅>=3.5% => +5分 (B5)
  //   连续3日跌幅>=3.5% => +10分 (B6)

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

    // ── 确定性加分 (最高 15 分) — 从远程JSON获取或回退到本地默认值 ──
  // 4维度12指标，每月初更新 GitHub Gist 中的 JSON 配置即可
  // ============================================================
  // 【使用说明】在 GitHub Gist 中编辑 policy_scores.json 的 value 值
  // JSON 格式见 fetchPolicyScores() 返回值
  // ============================================================
  let certaintyScores = [
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

  // 如果有远程配置，按 name 合并 value 值
  if (remoteScores && Array.isArray(remoteScores)) {
    for (const remote of remoteScores) {
      if (remote.name != null && remote.value != null) {
        const local = certaintyScores.find(s => s.name === remote.name);
        if (local) {
          local.value = Math.min(Math.max(remote.value, 0), local.max);
        }
      }
    }
  }

  let certaintyBonus = 0;
  const certaintyDetails = [];
  for (const s of certaintyScores) {
    const score = Math.min(Math.max(s.value, 0), s.max);
    if (score > 0) {
      certaintyBonus += score;
      certaintyDetails.push(`${s.name}+${score.toFixed(1)}`);
    }
  }
  if (certaintyBonus > 0) {
    bonusItems.push({ name: '确定性加分', score: certaintyBonus, detail: certaintyDetails.join(' ') });
    bonusTotal += certaintyBonus;
  }

  return { bonusTotal, bonusItems };
}

// ── 扣分项计算 (非奸即盗) ──

function calcDeductions(stock, klines, todaySSE) {
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
  // 今日大盘-2.26%，如果个股涨停则触发
  if (chgPct >= 9.5 && todaySSE <= -2) {
    deductions.push({ name: '逆势独木难支', score: -3, detail: `大盘${todaySSE.toFixed(2)}%,个股涨停` });
    totalDed += 3;
  }

  // 13. 逆势独木难支 (-3) — 大盘跌超2%且板块跌超3%
  // 今日大盘-2.26%，板块数据不确定，暂不扣

  // 汇总（扣至0为止）
  return { totalDed: Math.min(totalDed, 100), deductions };
}

// ── 主流程 ──

async function main() {
  console.log(`
╔══════════════════════════════════════════════════╗
║     超短线量化选股助手 v${SCRIPT_VERSION}                    ║
║     总资金：${String(TOTAL_FUNDS).padStart(8)} 元                    ║
║     交易标的：沪/深主板 + 创业板                 ║
╚══════════════════════════════════════════════════╝
`);

    // 自动更新检查（月初/月中从Gist拉取完整脚本）
    await checkUpdate(true);

    // 从 GitHub Gist 获取确定性加分配置（JSON加分项）
    console.log("  📡 检查确定性加分配置...");
    const remoteScores = fetchPolicyScores();
    if (!remoteScores) {
      console.log("  ⚠️ 无法获取远程配置，使用本地默认值（全0分）");
    } else {
      console.log("  ✅ 远程配置已加载");
    }

  const startTime = Date.now();

  // 今日大盘涨跌幅（从北向数据获取，硬编码为最近一个交易日数据）
  // TODO: 可通过 npx stock-sdk quote 000001 -q 获取上证实时涨跌幅
  const todaySSE = -2.26;

  // Step 1: 获取候选股
  const candidates = await getCandidates();
  if (candidates.length === 0) {
    console.log('\n❌ 没有找到候选股，请检查网络或稍后重试');
    return;
  }

  // 截取前 MAX_CANDIDATES 只
  const toAnalyze = candidates.slice(0, MAX_CANDIDATES);
  console.log(`\n🔎 详细分析 ${toAnalyze.length} 只候选股...\n`);

  const results = [];

  for (let i = 0; i < toAnalyze.length; i++) {
    const stock = toAnalyze[i];
    const code = stock.code;
    const name = stock.name;

    process.stdout.write(`  [${i+1}/${toAnalyze.length}] 🔍 ${code} ${name} ... `);

    // 获取技术指标 K 线
    const klines = getIndicators(code);
    if (!klines || klines.length < 60) {
      console.log('⚠️ K线数据不足');
      continue;
    }

    // 获取行情
    const quote = getQuote(code);

    // 硬门槛检查
    const hardFilter = checkHardFilters(stock, klines);
    if (!hardFilter.pass) {
      console.log(`❌ ${hardFilter.reason}`);
      continue;
    }

    // 计算基础分
    const { baseScore, scores, details } = calcBaseScore(stock, klines, quote, null, null);

    // 计算加分项
    const { bonusTotal, bonusItems } = calcBonus(klines, stock, todaySSE, remoteScores);

    // 计算扣分项
    const { totalDed, deductions } = calcDeductions(stock, klines, todaySSE);

    // 总分
    const finalScore = Math.max(0, baseScore + bonusTotal - totalDed);
    const effectiveDed = Math.min(totalDed, baseScore + bonusTotal); // 扣至0为止

    // 等级 — 核心原则：基础分<68意味着个股技术形态不过关，即使加分再多也应放弃
    let level, suggestion;
    if (baseScore < 68) {
      level = 'D'; suggestion = '放弃(基础分<68，技术形态不过关)';
    } else if (finalScore >= 90) { level = 'A'; suggestion = '强势共振，可出手，仓位3-4成'; }
    else if (finalScore >= 75) { level = 'B'; suggestion = '基本合格，轻仓试错1-2成'; }
    else if (finalScore >= 60) { level = 'C'; suggestion = '勉强及格，建议放弃'; }
    else { level = 'D'; suggestion = '放弃'; }

    console.log(`✅ 基础${baseScore}/100 +${bonusTotal} -${effectiveDed} = ${finalScore}分 [${level}]`);

    results.push({
      code, name,
      price: stock.price || quote?.price || (klines[klines.length-1]?.close) || 0,
      changePercent: stock.changePercent ?? (klines[klines.length-1]?.changePercent) ?? 0,
      industry: stock.industry || '',
      continuousBoard: stock.continuousBoardCount || 0,
      turnoverRate: stock.turnoverRate,
      baseScore,
      bonusTotal,
      deductionTotal: effectiveDed,
      finalScore,
      level,
      suggestion,
      details: details.join(' | '),
      bonusItems,
      deductions,
      scores,
      klineLatest: klines[klines.length - 1]
    });

    // 避免请求过快
    if (i < toAnalyze.length - 1) await sleep(200);
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
  <div class="meta">生成时间：${dateStr} ${timeStr} | 总资金：7万元 | 标的：沪/深主板</div>
</div>
<div class="summary">
  <div class="summary-item"><div class="num">${top10.length}</div><div class="label">输出个股</div></div>
  <div class="summary-item"><div class="num">${allResults.length}</div><div class="label">通过筛选</div></div>
  <div class="summary-item"><div class="num">${allResults.filter(r => r.level === 'A').length}</div><div class="label">A级推荐</div></div>
  <div class="summary-item"><div class="num">${allResults.filter(r => r.level === 'B').length}</div><div class="label">B级关注</div></div>
</div>
<table>
<thead>
<tr>
  <th>#</th><th>代码</th><th>名称</th><th>行业</th><th>连板</th><th>换手</th>
  <th>基础</th><th>加分</th><th>扣分</th><th>总分</th><th>等级</th><th>建议</th><th>明细</th>
</tr>
</thead>
<tbody>
${rows}
</tbody>
</table>
<div class="footer">
  ⚠️ 本结果仅供参考，不构成投资建议。股市有风险，投资需谨慎。<br>
  💡 A级(≥90)可出手 | B级(75-89)轻仓试错 | C级(60-74)建议放弃 | D级(<60)放弃
</div>
</body>
</html>`;

  fs.writeFileSync(OUTPUT_FILE, html, 'utf-8');
}

// ── 启动 ──

main().catch(err => {
  console.error('\n❌ 选股出错:', err.message);
  process.exit(1);
});
