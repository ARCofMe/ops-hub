import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("FieldDesk App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows setup guidance when technician config is missing", () => {
    render(<App />);
    expect(screen.getByText("Setup Required")).toBeInTheDocument();
    expect(screen.getByText(/technician subject/i)).toBeInTheDocument();
  });

  it("loads the technician queue and job detail from Ops Hub", async () => {
    window.localStorage.setItem(
      "fielddesk-web-config",
      JSON.stringify({
        apiBase: "http://127.0.0.1:8787",
        apiToken: "token",
        technicianSubject: "bf:123",
        themeMode: "dark",
      })
    );

    global.fetch = vi.fn(async (url) => {
      if (String(url).endsWith("/tech/me/today")) {
        return response([{ id: "100", customerName: "Pat Smith", address: "1 Main St", appointmentWindow: "8-10", status: "Scheduled" }]);
      }
      if (String(url).endsWith("/tech/jobs/100")) {
        return response({ id: "100", customerName: "Pat Smith", address: "1 Main St", appointmentWindow: "8-10", status: "Scheduled" });
      }
      if (String(url).endsWith("/tech/jobs/100/timeline")) {
        return response([{ occurredAt: "2026-04-23T08:00:00Z", summary: "Assigned", source: "ops_hub" }]);
      }
      if (String(url).endsWith("/tech/jobs/100/parts")) {
        return response({ stageLabel: "Requested", status: "open", nextAction: "Await office review" });
      }
      if (String(url).endsWith("/tech/jobs/100/photos")) {
        return response({ mailboxStatus: "ok", foundTags: ["before"], missingTags: ["after"] });
      }
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText("Pat Smith").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getByText(/Await office review/)).toBeInTheDocument();
    });
    expect(screen.getByText("Active Job")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
  });

  it("saves settings and pings Ops Hub health", async () => {
    global.fetch = vi.fn(async (url) => {
      if (String(url).endsWith("/health")) return response({ ok: true });
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);
    fireEvent.change(screen.getByLabelText("Ops Hub API base"), { target: { value: "http://127.0.0.1:8787" } });
    fireEvent.change(screen.getByLabelText("Technician API token"), { target: { value: "token" } });
    fireEvent.change(screen.getByLabelText("Technician subject"), { target: { value: "bf:321" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));

    await waitFor(() => {
      expect(screen.getByText("Ops Hub technician API reachable.")).toBeInTheDocument();
    });
  });
});

function response(payload) {
  return {
    ok: true,
    text: async () => JSON.stringify(payload),
  };
}
