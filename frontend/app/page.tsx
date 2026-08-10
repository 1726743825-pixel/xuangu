import { Suspense } from "react";
import { Dashboard } from "@/components/dashboard/Dashboard";

export default function HomePage() {
  return <Suspense><Dashboard /></Suspense>;
}
