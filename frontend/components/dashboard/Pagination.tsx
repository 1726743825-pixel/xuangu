type PaginationProps = {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
};

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, total);

  return (
    <div className="flex flex-col gap-3 border-t border-slate-200 px-5 py-4 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between">
      <span>显示 {start}–{end} 条，共 {total} 条</span>
      <div className="flex items-center gap-2">
        <button className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium text-slate-600 disabled:cursor-not-allowed disabled:opacity-40" disabled={page <= 1} onClick={() => onPageChange(page - 1)} type="button">上一页</button>
        <span className="min-w-20 text-center">{page} / {totalPages}</span>
        <button className="rounded-lg border border-slate-200 px-3 py-1.5 font-medium text-slate-600 disabled:cursor-not-allowed disabled:opacity-40" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} type="button">下一页</button>
      </div>
    </div>
  );
}
