export type SelectionItem = {
  code: string;
  name: string;
  trade_date: string;
  price: number | null;
  selection_price: number | null;
  selection_price_date: string | null;
  current_price: number | null;
  current_price_as_of: string | null;
  change_pct: number | null;
  score: number | null;
  display_score?: number | null;
  display_score_max?: number | null;
  strategy_name: string;
  industry: string | null;
  reasons: string[];
  rating_level?: string | null;
  rating?: string | null;
  indicators: Record<string, unknown>;
};

export type StockSummary = {
  code: string;
  name: string;
  industry: string | null;
  list_date?: string | null;
  is_st?: boolean;
};

export type SelectionPage = {
  date: string;
  items: SelectionItem[];
  count: number;
};

export type StockPage = {
  items: StockSummary[];
  page: number;
  size: number;
  total: number;
};

export type MarketIndexItem = {
  name: string;
  code: string;
  price: number | null;
  change_pct: number | null;
  as_of: string | null;
};

export type MarketIndices = {
  items: MarketIndexItem[];
};
