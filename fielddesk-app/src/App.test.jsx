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
        return response({
          mailboxStatus: "ok",
          foundTags: ["before"],
          missingTags: ["after"],
          records: [{ subject: "SR-100 photos", fromEmail: "tech@example.com", receivedAt: "2026-04-25T10:00:00Z", attachmentCount: 2, attachmentNames: ["sr-100-before.jpg"] }],
        });
      }
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText("Pat Smith").length).toBeGreaterThan(0);
    });
    await waitFor(() => {
      expect(screen.getAllByText(/Await office review/).length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Active Job")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
    expect(screen.getByText("Mailbox records: 1")).toBeInTheDocument();
  });

  it("filters the visible queue by search text", async () => {
    window.localStorage.setItem(
      "fielddesk-web-config",
      JSON.stringify({
        apiBase: "http://127.0.0.1:8787/",
        apiToken: "token",
        technicianSubject: "bf:123",
        themeMode: "dark",
      })
    );

    global.fetch = vi.fn(async (url) => {
      if (String(url).endsWith("/tech/me/today")) {
        return response([
          { id: "100", customerName: "Pat Smith", address: "1 Main St", appointmentWindow: "8-10", status: "Scheduled" },
          { id: "101", customerName: "Jordan Lake", address: "2 Broad St", appointmentWindow: "10-12", status: "Scheduled" },
        ]);
      }
      if (String(url).includes("/tech/jobs/100/timeline")) return response([]);
      if (String(url).includes("/tech/jobs/100/parts")) return response({});
      if (String(url).includes("/tech/jobs/100/photos")) return response({});
      if (String(url).includes("/tech/jobs/100")) return response({ id: "100", customerName: "Pat Smith", status: "Scheduled" });
      if (String(url).includes("/tech/jobs/101/timeline")) return response([]);
      if (String(url).includes("/tech/jobs/101/parts")) return response({});
      if (String(url).includes("/tech/jobs/101/photos")) return response({});
      if (String(url).includes("/tech/jobs/101")) return response({ id: "101", customerName: "Jordan Lake", status: "Scheduled" });
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Jordan Lake")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("Customer, SR, address"), { target: { value: "Jordan" } });

    expect(screen.getByText("Jordan Lake")).toBeInTheDocument();
    expect(screen.getByText("Visible: 1")).toBeInTheDocument();
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

  it("validates malformed config before pinging", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "Settings" })[0]);
    fireEvent.change(screen.getByLabelText("Ops Hub API base"), { target: { value: "127.0.0.1:8787" } });
    fireEvent.change(screen.getByLabelText("Technician API token"), { target: { value: "token" } });
    fireEvent.change(screen.getByLabelText("Technician subject"), { target: { value: "bf:321" } });
    fireEvent.click(screen.getByRole("button", { name: "Check connection" }));

    await waitFor(() => {
      expect(screen.getByText("Ops Hub API base must start with http:// or https://.")).toBeInTheDocument();
    });
  });

  it("uploads native camera captures through the web client", async () => {
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
      if (String(url).endsWith("/tech/jobs/100")) return response({ id: "100", customerName: "Pat Smith", status: "Scheduled" });
      if (String(url).endsWith("/tech/jobs/100/timeline")) return response([]);
      if (String(url).endsWith("/tech/jobs/100/parts")) return response({});
      if (String(url).endsWith("/tech/jobs/100/photos")) return response({ enabled: true, totalPhotos: 1, foundTags: ["before"], missingTags: [] });
      if (String(url).endsWith("/tech/jobs/100/photos/upload")) return response({ success: true, message: "Photo uploaded." });
      throw new Error(`Unexpected URL ${url}`);
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText("Pat Smith").length).toBeGreaterThan(0);
    });

    window.dispatchEvent(
      new CustomEvent("fielddesk:native-photo", {
        detail: {
          srId: "100",
          label: "before",
          filename: "sr-100-before.jpg",
          contentType: "image/jpeg",
          dataBase64: "ZmFrZQ==",
        },
      })
    );

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/tech\/jobs\/100\/photos\/upload$/),
        expect.objectContaining({ method: "POST" })
      );
    });
    await waitFor(() => {
      expect(window.localStorage.getItem("fielddesk-photo-gallery-100") || "").toContain("sr-100-before.jpg");
    });
  });
});

function response(payload) {
  return {
    ok: true,
    text: async () => JSON.stringify(payload),
  };
}
