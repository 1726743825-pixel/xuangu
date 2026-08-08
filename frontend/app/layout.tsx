import "./globals.css";

export const metadata = { title: "选股 · 每日选股台", description: "清晰、可回溯的 A 股选股工作台" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
