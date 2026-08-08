'use strict';

const http = require('http');
const https = require('https');

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
  '(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36';
const DEFAULT_TIMEOUT_MS = 15000;
const EASTMONEY_PRIMARY = 'push2.eastmoney.com';
const EASTMONEY_BACKUP = 'push2delay.eastmoney.com';
const EASTMONEY_MIN_INTERVAL_MS = 1200;
const ZT_POOL_UT = '7eea3edcaed734bea9cbfc24409ed989';

const defaultAgent = new https.Agent({
  keepAlive: true,
  rejectUnauthorized: false,
});

const eastmoneyAgent = new https.Agent({
  keepAlive: true,
  maxSockets: 2,
  rejectUnauthorized: false,
});

let eastmoneyLastCallAt = 0;
let eastmoneyQueue = Promise.resolve();

const quoteCache = new Map();
const klineCache = new Map();
const stockInfoCache = new Map();
const conceptBlockCache = new Map();
const fundFlowCache = new Map();
const stockDetailCache = new Map();
const sectorConstituentCache = new Map();

let sectorListPromise = null;
let conceptListPromise = null;
let cninfoOrgMapPromise = null;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toNumber(value) {
  if (
    value === null ||
    value === undefined ||
    value === '' ||
    value === '-' ||
    Number.isNaN(value)
  ) {
    return null;
  }

  const text = String(value).replace(/,/g, '').trim();
  if (!text) return null;

  const parsed = Number.parseFloat(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value, digits = 2) {
  const factor = 10 ** digits;
  return Math.round((Number(value) || 0) * factor) / factor;
}

function scaledPrice(value, factor = 100) {
  const number = toNumber(value);
  return number == null ? null : number / factor;
}

function normalizeDiff(diff) {
  if (Array.isArray(diff)) return diff;
  if (diff && typeof diff === 'object') return Object.values(diff);
  return [];
}

function buildSecid(code) {
  return code.startsWith('6') ? `1.${code}` : `0.${code}`;
}

function buildTencentSymbol(code) {
  if (code.startsWith('6') || code.startsWith('9')) return `sh${code}`;
  if (code.startsWith('8')) return `bj${code}`;
  return `sz${code}`;
}

function todayStr() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

function formatDate(value) {
  const text = String(value || '');
  if (/^\d{8}$/.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`;
  }
  return text;
}

function formatZtTime(value) {
  const text = String(value || '').padStart(6, '0');
  return `${text.slice(0, 2)}:${text.slice(2, 4)}:${text.slice(4, 6)}`;
}

function mergeCandidate(base, incoming) {
  const merged = { ...(base || {}) };

  for (const [key, value] of Object.entries(incoming || {})) {
    if (value === null || value === undefined) continue;
    if (typeof value === 'string' && value.trim() === '') continue;
    merged[key] = value;
  }

  const baseCount = Number(base?.continuousBoardCount) || 0;
  const nextCount = Number(incoming?.continuousBoardCount) || 0;
  merged.continuousBoardCount = Math.max(baseCount, nextCount);

  return merged;
}

function pickFirst(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== '') return value;
  }
  return null;
}

function decodeBuffer(buffer, encoding = 'utf8') {
  if (!buffer) return '';
  if (/^gb/i.test(encoding)) {
    return new TextDecoder('gb18030').decode(buffer);
  }
  return buffer.toString(encoding);
}

function isRetriableStatus(statusCode) {
  return [429, 500, 502, 503, 504].includes(statusCode);
}

async function requestBuffer(url, options = {}) {
  const {
    method = 'GET',
    headers = {},
    body = null,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retries = 2,
    agent = defaultAgent,
  } = options;

  let currentUrl = url;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await new Promise((resolve, reject) => {
        const parsed = new URL(currentUrl);
        const transport = parsed.protocol === 'http:' ? http : https;
        const requestOptions = {
          protocol: parsed.protocol,
          hostname: parsed.hostname,
          port: parsed.port || undefined,
          path: `${parsed.pathname}${parsed.search}`,
          method,
          headers,
          timeout: timeoutMs,
          agent: parsed.protocol === 'https:' ? agent : undefined,
          rejectUnauthorized: false,
        };

        const req = transport.request(requestOptions, (res) => {
          const chunks = [];
          res.on('data', (chunk) => chunks.push(chunk));
          res.on('end', () => {
            resolve({
              statusCode: res.statusCode || 0,
              headers: res.headers || {},
              buffer: Buffer.concat(chunks),
            });
          });
        });

        req.on('timeout', () => {
          req.destroy(new Error(`timeout after ${timeoutMs}ms`));
        });
        req.on('error', reject);

        if (body) req.write(body);
        req.end();
      });

      if (
        response.statusCode >= 300 &&
        response.statusCode < 400 &&
        response.headers.location
      ) {
        currentUrl = new URL(response.headers.location, currentUrl).toString();
        continue;
      }

      if (response.statusCode >= 200 && response.statusCode < 300) {
        return response.buffer;
      }

      if (attempt < retries && isRetriableStatus(response.statusCode)) {
        await sleep(400 * (attempt + 1));
        continue;
      }

      throw new Error(`HTTP ${response.statusCode}`);
    } catch (error) {
      if (attempt >= retries) throw error;
      await sleep(400 * (attempt + 1));
    }
  }

  throw new Error(`request failed: ${url}`);
}

async function requestText(url, options = {}) {
  const encoding = options.encoding || 'utf8';
  const buffer = await requestBuffer(url, options);
  return decodeBuffer(buffer, encoding);
}

async function requestJson(url, options = {}) {
  const text = await requestText(url, options);
  return JSON.parse(text);
}

function runEastmoneyTask(task) {
  const runner = eastmoneyQueue.then(async () => {
    const waitMs =
      eastmoneyLastCallAt + EASTMONEY_MIN_INTERVAL_MS - Date.now();

    if (waitMs > 0) {
      await sleep(waitMs + 100 + Math.floor(Math.random() * 250));
    }

    try {
      return await task();
    } finally {
      eastmoneyLastCallAt = Date.now();
    }
  });

  eastmoneyQueue = runner.catch(() => undefined);
  return runner;
}

async function eastmoneyText(url, options = {}) {
  const {
    headers = {},
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retries = 2,
    allowBackup = true,
  } = options;

  return runEastmoneyTask(async () => {
    const mergedHeaders = {
      'User-Agent': UA,
      Referer: 'https://quote.eastmoney.com/',
      ...headers,
    };

    try {
      return await requestText(url, {
        ...options,
        headers: mergedHeaders,
        timeoutMs,
        retries,
        agent: eastmoneyAgent,
        encoding: 'utf8',
      });
    } catch (error) {
      if (allowBackup && url.includes(EASTMONEY_PRIMARY)) {
        const backupUrl = url.replace(EASTMONEY_PRIMARY, EASTMONEY_BACKUP);
        return requestText(backupUrl, {
          ...options,
          headers: mergedHeaders,
          timeoutMs,
          retries: 1,
          agent: eastmoneyAgent,
          encoding: 'utf8',
        });
      }
      throw error;
    }
  });
}

async function eastmoneyJson(url, options = {}) {
  const text = await eastmoneyText(url, options);
  return JSON.parse(text);
}

async function getTencentQuoteBatch(codes) {
  const uniqueCodes = Array.from(
    new Set((codes || []).map((item) => String(item || '').trim()).filter(Boolean)),
  );
  const missingCodes = uniqueCodes.filter((code) => !quoteCache.has(code));

  if (missingCodes.length > 0) {
    try {
      const symbols = missingCodes.map(buildTencentSymbol);
      const url = `https://qt.gtimg.cn/q=${symbols.join(',')}`;
      const text = await requestText(url, {
        headers: { 'User-Agent': UA },
        encoding: 'gb18030',
      });

      for (const line of text.split(';')) {
        if (!line.includes('"')) continue;
        const key = line.split('=')[0].split('_').pop();
        const parts = line.split('"');
        if (!parts[1]) continue;

        const values = parts[1].split('~');
        if (values.length < 53 || !key) continue;

        const code = key.slice(2);
        quoteCache.set(code, {
          code,
          name: values[1] || '',
          price: toNumber(values[3]),
          lastClose: toNumber(values[4]),
          open: toNumber(values[5]),
          changeAmount: toNumber(values[31]),
          changePercent: toNumber(values[32]),
          high: toNumber(values[33]),
          low: toNumber(values[34]),
          amountWan: toNumber(values[37]),
          turnoverRate: toNumber(values[38]),
          peTtm: toNumber(values[39]),
          amplitudePct: toNumber(values[43]),
          mcapYi: toNumber(values[44]),
          floatMcapYi: toNumber(values[45]),
          pb: toNumber(values[46]),
          limitUp: toNumber(values[47]),
          limitDown: toNumber(values[48]),
          volRatio: toNumber(values[49]),
          peStatic: toNumber(values[52]),
        });
      }
    } catch {
      // fall through and mark misses as null
    }

    for (const code of missingCodes) {
      if (!quoteCache.has(code)) quoteCache.set(code, null);
    }
  }

  const result = {};
  for (const code of uniqueCodes) {
    result[code] = quoteCache.get(code) || null;
  }
  return result;
}

async function getQuote(code) {
  const quotes = await getTencentQuoteBatch([code]);
  const quote = quotes[code] || null;
  if (!quote) return null;

  return {
    code: quote.code,
    name: quote.name,
    price: quote.price,
    changePercent: quote.changePercent,
    turnoverRate: quote.turnoverRate,
    amount: quote.amountWan != null ? quote.amountWan * 10000 : null,
    amountWan: quote.amountWan,
    floatMarketValue:
      quote.floatMcapYi != null ? quote.floatMcapYi * 1e8 : null,
    marketValue: quote.mcapYi != null ? quote.mcapYi * 1e8 : null,
    limitUp: quote.limitUp,
    limitDown: quote.limitDown,
    volRatio: quote.volRatio,
    peTtm: quote.peTtm,
    pb: quote.pb,
  };
}

function calcMovingAverage(values, period) {
  const result = new Array(values.length).fill(null);
  if (!Array.isArray(values) || values.length < period) return result;

  let rolling = 0;
  for (let index = 0; index < values.length; index++) {
    rolling += values[index];
    if (index >= period) rolling -= values[index - period];
    if (index >= period - 1) result[index] = rolling / period;
  }
  return result;
}

function calcIndicators(klines) {
  const closes = klines.map((item) => item.close || 0);
  const ma5 = calcMovingAverage(closes, 5);
  const ma10 = calcMovingAverage(closes, 10);
  const ma20 = calcMovingAverage(closes, 20);
  const ma60 = calcMovingAverage(closes, 60);

  const ema = (values, period) => {
    const output = [];
    const k = 2 / (period + 1);

    for (let index = 0; index < values.length; index++) {
      if (index === 0) {
        output.push(values[index]);
        continue;
      }
      output.push(values[index] * k + output[index - 1] * (1 - k));
    }
    return output;
  };

  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const dif = ema12.map((value, index) => value - ema26[index]);
  const dea = ema(dif, 9);
  const macd = dif.map((value, index) => (value - dea[index]) * 2);

  const kSeries = [];
  const dSeries = [];
  const jSeries = [];
  let prevK = 50;
  let prevD = 50;

  for (let index = 0; index < klines.length; index++) {
    const start = Math.max(0, index - 8);
    const window = klines.slice(start, index + 1);
    const highest = Math.max(...window.map((item) => item.high || 0));
    const lowest = Math.min(...window.map((item) => item.low || 0));
    const rsv =
      highest !== lowest
        ? (((klines[index].close || 0) - lowest) / (highest - lowest)) * 100
        : 50;
    const kValue = (2 / 3) * prevK + (1 / 3) * rsv;
    const dValue = (2 / 3) * prevD + (1 / 3) * kValue;

    kSeries.push(kValue);
    dSeries.push(dValue);
    jSeries.push(3 * kValue - 2 * dValue);

    prevK = kValue;
    prevD = dValue;
  }

  for (let index = 0; index < klines.length; index++) {
    const item = klines[index];
    item.ma = {
      ma5: pickFirst(item.ma?.ma5, ma5[index]),
      ma10: pickFirst(item.ma?.ma10, ma10[index]),
      ma20: pickFirst(item.ma?.ma20, ma20[index]),
      ma60: ma60[index],
    };
    item.macd = { dif: dif[index], dea: dea[index], macd: macd[index] };
    item.kdj = { k: kSeries[index], d: dSeries[index], j: jSeries[index] };
  }

  return klines;
}

async function getIndicators(code, limit = 150) {
  if (klineCache.has(code)) return klineCache.get(code);

  try {
    const params = new URLSearchParams({
      all: '1',
      isIndex: 'false',
      isBk: 'false',
      isBlock: 'false',
      isFutures: 'false',
      isStock: 'true',
      newFormat: '1',
      group: 'quotation_kline_ab',
      finClientType: 'pc',
      code,
      start_time: '',
      ktype: '1',
    });

    const data = await requestJson(
      `https://finance.pae.baidu.com/selfselect/getstockquotation?${params.toString()}`,
      {
        headers: {
          'User-Agent': UA,
          Accept: 'application/vnd.finance-web.v1+json',
          Origin: 'https://gushitong.baidu.com',
          Referer: 'https://gushitong.baidu.com/',
        },
      },
    );

    if (String(data?.ResultCode ?? data?.Result?.ResultCode ?? -1) !== '0') {
      klineCache.set(code, []);
      return [];
    }

    const marketData = data?.Result?.newMarketData || {};
    const keys = marketData.keys || [];
    const keyIndex = Object.fromEntries(keys.map((key, index) => [key, index]));
    const rows = String(marketData.marketData || '')
      .split(';')
      .filter(Boolean);

    const slicedRows = rows.slice(-Math.max(limit, 60));
    const klines = slicedRows.map((line, index) => {
      const parts = line.split(',');
      const prevCloseFromRow = toNumber(parts[keyIndex.preClose]);
      const close = toNumber(parts[keyIndex.close]) || 0;
      const previousClose =
        prevCloseFromRow ||
        (index > 0 ? toNumber(slicedRows[index - 1].split(',')[keyIndex.close]) : null);

      return {
        date: parts[keyIndex.time] || '',
        open: toNumber(parts[keyIndex.open]) || 0,
        close,
        high: toNumber(parts[keyIndex.high]) || 0,
        low: toNumber(parts[keyIndex.low]) || 0,
        volume: Math.round(toNumber(parts[keyIndex.volume]) || 0),
        amount: toNumber(parts[keyIndex.amount]) || 0,
        changePercent:
          toNumber(parts[keyIndex.ratio]) ??
          (previousClose ? ((close - previousClose) / previousClose) * 100 : 0),
        turnoverRate: toNumber(parts[keyIndex.turnoverratio]) || 0,
        ma: {
          ma5: toNumber(parts[keyIndex.ma5avgprice]),
          ma10: toNumber(parts[keyIndex.ma10avgprice]),
          ma20: toNumber(parts[keyIndex.ma20avgprice]),
          ma60: null,
        },
        macd: {},
        kdj: {},
      };
    });

    const result = calcIndicators(klines);
    klineCache.set(code, result);
    return result;
  } catch {
    klineCache.set(code, []);
    return [];
  }
}

async function getMarketData() {
  try {
    const url =
      'https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f170,f113,f114,f58';
    const json = await eastmoneyJson(url);
    const data = json?.data;
    if (!data) return null;

    const riseCount = Number(data.f113) || 0;
    const fallCount = Number(data.f114) || 0;

    return {
      sseChangePercent: (Number(data.f170) || 0) / 100,
      price: (Number(data.f43) || 0) / 100,
      riseCount,
      fallCount,
      advDeclRatio: fallCount > 0 ? riseCount / fallCount : 0,
    };
  } catch {
    return null;
  }
}

async function getSectorList() {
  if (!sectorListPromise) {
    sectorListPromise = (async () => {
      try {
        const url =
          'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fs=m:90+t:2&fields=f12,f14,f3,f104,f105';
        const json = await eastmoneyJson(url);
        return normalizeDiff(json?.data?.diff).map((item) => ({
          bkCode: item.f12,
          name: item.f14,
          changePercent: toNumber(item.f3) || 0,
          riseCount: Number(item.f104) || 0,
          fallCount: Number(item.f105) || 0,
        }));
      } catch {
        return null;
      }
    })();
  }

  return sectorListPromise;
}

async function getConceptList() {
  if (!conceptListPromise) {
    conceptListPromise = (async () => {
      try {
        const url =
          'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1000&po=1&np=1&fltt=2&invt=2&fs=m:90+t:3+f:!50&fields=f12,f14,f3,f86,f87';
        const json = await eastmoneyJson(url);
        return normalizeDiff(json?.data?.diff).map((item) => ({
          bkCode: item.f12,
          name: item.f14,
          changePercent: toNumber(item.f3) || 0,
          riseCount: Number(item.f86) || 0,
          fallCount: Number(item.f87) || 0,
        }));
      } catch {
        return [];
      }
    })();
  }

  return conceptListPromise;
}

async function getSectorConstituents(sectorCode) {
  if (sectorConstituentCache.has(sectorCode)) {
    return sectorConstituentCache.get(sectorCode);
  }

  try {
    const url =
      `https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2&` +
      `fs=b:${sectorCode}&fields=f12,f14,f3`;
    const json = await eastmoneyJson(url);
    const result = normalizeDiff(json?.data?.diff).map((item, index) => ({
      rank: index + 1,
      code: item.f12,
      name: item.f14,
      changePercent: toNumber(item.f3) || 0,
    }));

    sectorConstituentCache.set(sectorCode, result);
    return result;
  } catch {
    sectorConstituentCache.set(sectorCode, null);
    return null;
  }
}

async function getStockInfo(code) {
  if (stockInfoCache.has(code)) return stockInfoCache.get(code);

  try {
    const url =
      `https://push2.eastmoney.com/api/qt/stock/get?fltt=2&invt=2&` +
      `fields=f57,f58,f84,f85,f127,f116,f117,f189,f43&secid=${buildSecid(code)}`;
    const json = await eastmoneyJson(url);
    const data = json?.data || {};
    const result = {
      code: data.f57 || code,
      name: data.f58 || '',
      industry: data.f127 === '-' ? '' : data.f127 || '',
      totalShares: Number(data.f84) || 0,
      floatShares: Number(data.f85) || 0,
      marketValue: Number(data.f116) || 0,
      floatMarketValue: Number(data.f117) || 0,
      listDate: formatDate(data.f189),
      price: scaledPrice(data.f43),
    };

    stockInfoCache.set(code, result);
    return result;
  } catch {
    const fallback = {
      code,
      name: '',
      industry: '',
      totalShares: 0,
      floatShares: 0,
      marketValue: 0,
      floatMarketValue: 0,
      listDate: '',
      price: null,
    };
    stockInfoCache.set(code, fallback);
    return fallback;
  }
}

async function getConceptBlocks(code) {
  if (conceptBlockCache.has(code)) return conceptBlockCache.get(code);

  try {
    const params = new URLSearchParams({
      fltt: '2',
      invt: '2',
      secid: buildSecid(code),
      spt: '3',
      pi: '0',
      pz: '200',
      po: '1',
      fields: 'f12,f14,f3,f128',
    });

    const json = await eastmoneyJson(
      `https://push2.eastmoney.com/api/qt/slist/get?${params.toString()}`,
    );
    const boards = normalizeDiff(json?.data?.diff).map((item) => ({
      code: item.f12 || '',
      name: item.f14 || '',
      changePercent: toNumber(item.f3) || 0,
      leaderStock: item.f128 || '',
    }));

    conceptBlockCache.set(code, boards);
    return boards;
  } catch {
    conceptBlockCache.set(code, []);
    return [];
  }
}

async function getFundFlowMinute(code) {
  if (fundFlowCache.has(code)) return fundFlowCache.get(code);

  try {
    const params = new URLSearchParams({
      secid: buildSecid(code),
      klt: '1',
      fields1: 'f1,f2,f3,f7',
      fields2: 'f51,f52,f53,f54,f55,f56,f57',
    });

    const json = await eastmoneyJson(
      `https://push2.eastmoney.com/api/qt/stock/fflow/kline/get?${params.toString()}`,
      {
        headers: {
          Referer: 'https://quote.eastmoney.com/',
          Origin: 'https://quote.eastmoney.com',
        },
      },
    );

    const result = (json?.data?.klines || []).map((line) => {
      const parts = String(line).split(',');
      return {
        time: parts[0] || '',
        mainNet: toNumber(parts[1]) || 0,
        smallNet: toNumber(parts[2]) || 0,
        midNet: toNumber(parts[3]) || 0,
        largeNet: toNumber(parts[4]) || 0,
        superNet: toNumber(parts[5]) || 0,
      };
    });

    fundFlowCache.set(code, result);
    return result;
  } catch {
    fundFlowCache.set(code, []);
    return [];
  }
}

async function getStockDetail(code) {
  if (stockDetailCache.has(code)) return stockDetailCache.get(code);

  const detailPromise = (async () => {
    const settled = await Promise.allSettled([
      getQuote(code),
      getStockInfo(code),
      getConceptBlocks(code),
      getFundFlowMinute(code),
    ]);
    const quote = settled[0].status === 'fulfilled' ? settled[0].value : null;
    const stockInfo = settled[1].status === 'fulfilled' ? settled[1].value : null;
    const conceptBlocks = settled[2].status === 'fulfilled' ? settled[2].value : [];
    const minuteFlow = settled[3].status === 'fulfilled' ? settled[3].value : [];

    const lastFlow =
      Array.isArray(minuteFlow) && minuteFlow.length > 0
        ? minuteFlow[minuteFlow.length - 1]
        : null;
    const amountYuan = (quote?.amountWan || 0) * 10000;
    const largeOrderNet =
      lastFlow != null ? (lastFlow.largeNet || 0) + (lastFlow.superNet || 0) : null;

    return {
      code,
      name: pickFirst(stockInfo?.name, quote?.name, ''),
      industry: stockInfo?.industry || '',
      concepts: conceptBlocks.map((item) => item.name).filter(Boolean),
      mainNetInflow: lastFlow?.mainNet ?? null,
      mainForcePercent:
        amountYuan > 0 && lastFlow
          ? round((lastFlow.mainNet / amountYuan) * 100, 2)
          : null,
      largeOrderPercent:
        amountYuan > 0 && largeOrderNet != null
          ? round((largeOrderNet / amountYuan) * 100, 2)
          : null,
      changePercent: quote?.changePercent ?? null,
      turnoverRate: quote?.turnoverRate ?? null,
      marketValue: pickFirst(quote?.marketValue, stockInfo?.marketValue, null),
      floatMarketValue: pickFirst(
        quote?.floatMarketValue,
        stockInfo?.floatMarketValue,
        null,
      ),
      price: pickFirst(quote?.price, stockInfo?.price, null),
    };
  })();

  stockDetailCache.set(code, detailPromise);
  return detailPromise;
}

function getZtApiUrl(endpoint, sort, date) {
  const params = new URLSearchParams({
    ut: ZT_POOL_UT,
    dpt: 'wz.ztzt',
    Pageindex: '0',
    pagesize: '10000',
    sort,
    date,
  });
  return `https://push2ex.eastmoney.com/${endpoint}?${params.toString()}`;
}

async function getZtPool(date = todayStr()) {
  try {
    const json = await eastmoneyJson(getZtApiUrl('getTopicZTPool', 'fbt:asc', date));
    return (json?.data?.pool || []).map((item) => ({
      code: item.c,
      name: item.n,
      price: scaledPrice(item.p, 1000),
      changePercent: toNumber(item.zdp) || 0,
      floatMarketValue: toNumber(item.ltsz),
      turnoverRate: toNumber(item.hs) || 0,
      continuousBoardCount: Number(item.lbc) || 0,
      industry: item.hybk || '',
      sealFund: Number(item.fund) || 0,
      breakTimes: Number(item.zbc) || 0,
      firstSeal: formatZtTime(item.fbt),
      lastSeal: formatZtTime(item.lbt),
    }));
  } catch {
    return [];
  }
}

async function getYesterdayZtPool(date = todayStr()) {
  try {
    const json = await eastmoneyJson(
      getZtApiUrl('getYesterdayZTPool', 'zs:desc', date),
    );
    return (json?.data?.pool || []).map((item) => ({
      code: item.c,
      name: item.n,
      price: scaledPrice(item.p, 1000),
      changePercent: toNumber(item.zdp) || 0,
      turnoverRate: toNumber(item.hs) || 0,
      continuousBoardCount: Number(item.ylbc) || 0,
      industry: item.hybk || '',
      amplitude: toNumber(item.zf) || 0,
      speed: toNumber(item.zs) || 0,
      firstSeal: formatZtTime(item.yfbt),
    }));
  } catch {
    return [];
  }
}

async function getStrongPool(period = 'hour') {
  try {
    const url =
      `https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?` +
      new URLSearchParams({
        stock_type: 'a',
        type: period,
        list_type: 'normal',
      }).toString();

    const json = await requestJson(url, {
      headers: { 'User-Agent': UA },
    });

    return ((json?.data || {}).stock_list || [])
      .filter((item) => (toNumber(item.rise_and_fall) || 0) >= 0)
      .slice(0, 80)
      .map((item) => ({
        code: item.code,
        name: item.name,
        changePercent: toNumber(item.rise_and_fall) || 0,
        hotRank: Number(item.order) || 0,
        concepts: item?.tag?.concept_tag || [],
        hotTag: item?.tag?.popularity_tag || '',
      }));
  } catch {
    return [];
  }
}

async function getCandidates() {
  const [ztPool, strongPool, yesterdayPool] = await Promise.all([
    getZtPool(),
    getStrongPool('hour'),
    getYesterdayZtPool(),
  ]);

  const mergedMap = new Map();
  for (const pool of [ztPool, strongPool, yesterdayPool]) {
    for (const stock of pool) {
      const existing = mergedMap.get(stock.code);
      mergedMap.set(stock.code, mergeCandidate(existing, stock));
    }
  }

  const codes = Array.from(mergedMap.keys());
  const quoteMap = await getTencentQuoteBatch(codes);

  const candidates = codes.map((code) => {
    const stock = mergedMap.get(code);
    const quote = quoteMap[code] || null;
    return mergeCandidate(stock, {
      price: pickFirst(stock.price, quote?.price, null),
      changePercent: pickFirst(stock.changePercent, quote?.changePercent, null),
      turnoverRate: pickFirst(stock.turnoverRate, quote?.turnoverRate, null),
      floatMarketValue:
        stock.floatMarketValue ??
        (quote?.floatMcapYi != null ? quote.floatMcapYi * 1e8 : null),
      marketValue:
        stock.marketValue ??
        (quote?.mcapYi != null ? quote.mcapYi * 1e8 : null),
    });
  });

  return { candidates, yesterdayPool };
}

async function getZTPremium() {
  try {
    const yesterdayPool = await getYesterdayZtPool();
    const valid = yesterdayPool.filter(
      (item) => item.changePercent != null && Number.isFinite(item.changePercent),
    );
    if (valid.length === 0) return null;

    const total = valid.reduce(
      (sum, item) => sum + (Number(item.changePercent) || 0),
      0,
    );
    return total / valid.length;
  } catch {
    return null;
  }
}

async function eastmoneyDatacenter(
  reportName,
  filterStr,
  pageSize = 50,
  sortColumns = '',
  sortTypes = '-1',
) {
  const params = new URLSearchParams({
    reportName,
    columns: 'ALL',
    filter: filterStr,
    pageNumber: '1',
    pageSize: String(pageSize),
    sortColumns,
    sortTypes,
    source: 'WEB',
    client: 'WEB',
  });

  try {
    const json = await eastmoneyJson(
      `https://datacenter-web.eastmoney.com/api/data/v1/get?${params.toString()}`,
      {
        headers: {
          Referer: 'https://data.eastmoney.com/',
        },
      },
    );

    return json?.result?.data || [];
  } catch {
    return [];
  }
}

async function checkDragonTigerRetail(code) {
  const rows = await eastmoneyDatacenter(
    'RPT_DMSK_TSLS',
    `(SECURITY_CODE="${code}")`,
    50,
  );
  if (!rows.length) return null;

  const buySeats = rows.filter((item) => item.TRADE_TYPE === '买入');
  const retailCount = buySeats.filter((item) =>
    ['拉萨', '东方财富证券股份有限公司拉萨'].some((keyword) =>
      String(item.BRANCH_NAME || '').includes(keyword),
    ),
  ).length;

  if (retailCount >= 3) {
    return {
      name: '龙虎榜散户霸榜',
      score: -3,
      detail: `买入前5中拉萨系占${retailCount}席`,
    };
  }

  return null;
}

async function getCninfoOrgMap() {
  if (!cninfoOrgMapPromise) {
    cninfoOrgMapPromise = requestJson(
      'https://www.cninfo.com.cn/new/data/szse_stock.json',
      {
        headers: { 'User-Agent': UA },
      },
    )
      .then((json) => {
        const map = {};
        for (const item of json?.stockList || []) {
          if (item?.code && item?.orgId) map[item.code] = item.orgId;
        }
        return map;
      })
      .catch(() => ({}));
  }

  return cninfoOrgMapPromise;
}

function fallbackCninfoOrgId(code) {
  if (code.startsWith('6')) return `gssh0${code}`;
  if (code.startsWith('8') || code.startsWith('4')) return `gsbj0${code}`;
  return `gssz0${code}`;
}

async function getCninfoAnnouncements(code, pageSize = 30) {
  try {
    const orgMap = await getCninfoOrgMap();
    const orgId = orgMap[code] || fallbackCninfoOrgId(code);
    const body = new URLSearchParams({
      stock: `${code},${orgId}`,
      tabName: 'fulltext',
      pageSize: String(pageSize),
      pageNum: '1',
      column: '',
      category: '',
      plate: '',
      seDate: '',
      searchkey: '',
      secid: '',
      sortName: '',
      sortType: '',
      isHLtitle: 'true',
    }).toString();

    const text = await requestText(
      'https://www.cninfo.com.cn/new/hisAnnouncement/query',
      {
        method: 'POST',
        body,
        headers: {
          'User-Agent': UA,
          'Content-Type': 'application/x-www-form-urlencoded',
          Referer: 'https://www.cninfo.com.cn/new/disclosure',
          Origin: 'https://www.cninfo.com.cn',
        },
        encoding: 'utf8',
      },
    );

    const json = JSON.parse(text);
    return (json?.announcements || []).map((item) => {
      let date = '';
      if (item.announcementTime) {
        const local = new Date(item.announcementTime);
        const y = local.getFullYear();
        const m = String(local.getMonth() + 1).padStart(2, '0');
        const d = String(local.getDate()).padStart(2, '0');
        date = `${y}-${m}-${d}`;
      }
      return {
        title: item.announcementTitle || '',
        type: item.announcementTypeName || '',
        date,
      };
    });
  } catch {
    return [];
  }
}

async function checkAnnouncementRisk(code) {
  const announcements = await getCninfoAnnouncements(code, 30);
  if (!announcements.length) return null;

  const fiveDaysAgo = Date.now() - 5 * 24 * 60 * 60 * 1000;
  for (const item of announcements) {
    const title = String(item.title || '');
    const date = Date.parse(item.date || '');
    if (Number.isFinite(date) && date < fiveDaysAgo) continue;
    if (
      title.includes('减持') ||
      title.includes('解禁') ||
      title.includes('减持计划')
    ) {
      return {
        name: '股东减持/解禁',
        score: -5,
        detail: `${title.includes('解禁') ? '解禁' : '减持'}:${title.slice(0, 20)}`,
      };
    }
  }

  return null;
}

module.exports = {
  getCandidates,
  getIndicators,
  getQuote,
  getStockDetail,
  getMarketData,
  getSectorList,
  getConceptList,
  getSectorConstituents,
  getZTPremium,
  checkDragonTigerRetail,
  checkAnnouncementRisk,
};
