export type SelectionItem = {
  code: string;
  name: string;
  trade_date: string;
  price: number | null;
  change_pct: number | null;
  score: number | null;
  strategy_name: string;
  industry: string | null;
  reasons: string[];
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

export type SortKey = "code" | "name" | "price" | "change_pct" | "strategy_name";
export type SortDirection = "asc" | "desc";
