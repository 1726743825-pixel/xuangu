import "./globals.css";
import { ThemeProvider } from "@/components/theme/ThemeProvider";

export const metadata = { title: "选股 · 每日选股台", description: "清晰、可回溯的 A 股选股工作台" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="zh-CN" suppressHydrationWarning><body><ThemeProvider>{children}</ThemeProvider></body></html>;
}
