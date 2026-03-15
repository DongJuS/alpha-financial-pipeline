import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import Layout from "@/components/Layout";

describe("Layout navigation", () => {
  it("renders model management, long-term, and paper trading navigation items", () => {
    render(
      <MemoryRouter initialEntries={["/dashboard"]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<div>dashboard</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getAllByText("모델 관리").length).toBeGreaterThan(0);
    expect(screen.getAllByText("모의 투자").length).toBeGreaterThan(0);
    expect(screen.getAllByText("장기투자").length).toBeGreaterThan(0);
  });
});
