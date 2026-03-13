import { Suspense, lazy, type ReactNode } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Login from "@/pages/Login";
import Layout from "@/components/Layout";
import RequireAuth from "@/components/RequireAuth";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Strategy = lazy(() => import("@/pages/Strategy"));
const Portfolio = lazy(() => import("@/pages/Portfolio"));
const Market = lazy(() => import("@/pages/Market"));
const LongTerm = lazy(() => import("@/pages/LongTerm"));
const PaperTrading = lazy(() => import("@/pages/PaperTrading"));
const Settings = lazy(() => import("@/pages/Settings"));

function RouteFallback() {
  return (
    <div className="page-shell">
      <section className="card">
        <div className="h-6 w-36 skeleton" />
        <div className="mt-4 h-4 w-full skeleton" />
        <div className="mt-2 h-4 w-5/6 skeleton" />
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          <div className="h-40 skeleton" />
          <div className="h-40 skeleton" />
        </div>
      </section>
    </div>
  );
}

function withSuspense(page: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{page}</Suspense>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={withSuspense(<Dashboard />)} />
          <Route path="/strategy" element={withSuspense(<Strategy />)} />
          <Route path="/portfolio" element={withSuspense(<Portfolio />)} />
          <Route path="/market" element={withSuspense(<Market />)} />
          <Route path="/long-term" element={withSuspense(<LongTerm />)} />
          <Route path="/paper-trading" element={withSuspense(<PaperTrading />)} />
          <Route path="/settings" element={withSuspense(<Settings />)} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
