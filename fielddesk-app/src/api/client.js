const DEFAULT_BASE = (import.meta.env.VITE_OPS_HUB_API_BASE || "http://127.0.0.1:8787").replace(/\/$/, "");
const DEFAULT_TOKEN = import.meta.env.VITE_OPS_HUB_API_TOKEN || "";
const DEFAULT_SUBJECT = import.meta.env.VITE_TECHNICIAN_SUBJECT || "";

function parsePayload(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function buildErrorMessage(status, payload, fallbackText) {
  if (payload && typeof payload === "object" && "message" in payload && payload.message) {
    return `${status}: ${payload.message}`;
  }
  if (typeof payload === "string" && payload.trim()) return `${status}: ${payload}`;
  return `${status}: ${fallbackText || "Request failed."}`;
}

export function createFieldDeskApi(configProvider) {
  async function request(path, options = {}) {
    const config = configProvider();
    const controller = new AbortController();
    const timeoutMs = clampTimeout(config.timeoutMs);
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const hasBody = options.body !== undefined;
    try {
      const response = await fetch(`${config.apiBase}${path}`, {
        method: options.method || "GET",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${config.apiToken}`,
          "X-Technician-Subject": config.technicianSubject,
          ...(hasBody ? { "Content-Type": "application/json" } : {}),
        },
        body: hasBody ? JSON.stringify(options.body) : undefined,
        signal: controller.signal,
      });
      const text = await response.text();
      const payload = parsePayload(text);
      if (!response.ok) throw new Error(buildErrorMessage(response.status, payload, text));
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") throw new Error(`Ops Hub request timed out after ${Math.round(timeoutMs / 1000)}s.`);
      if (error instanceof TypeError) throw new Error("Could not reach Ops Hub. Check the API base URL and that ops-hub is running.");
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  return {
    health() {
      return request("/health");
    },
    getToday() {
      return request("/tech/me/today");
    },
    getJobs() {
      return request("/tech/jobs");
    },
    getJob(srId) {
      return request(`/tech/jobs/${encodePathPart(srId)}`);
    },
    getTimeline(srId) {
      return request(`/tech/jobs/${encodePathPart(srId)}/timeline`);
    },
    getParts(srId) {
      return request(`/tech/jobs/${encodePathPart(srId)}/parts`);
    },
    getPhotos(srId) {
      return request(`/tech/jobs/${encodePathPart(srId)}/photos`);
    },
    postCallAhead(srId, minutes = 30) {
      return request(`/tech/jobs/${encodePathPart(srId)}/call_ahead`, { method: "POST", body: { minutes } });
    },
    postStatus(srId, status) {
      return request(`/tech/jobs/${encodePathPart(srId)}/status`, { method: "POST", body: { status } });
    },
    postNote(srId, note) {
      return request(`/tech/jobs/${encodePathPart(srId)}/notes`, { method: "POST", body: { note } });
    },
    postParts(srId, details) {
      return request(`/tech/jobs/${encodePathPart(srId)}/parts`, { method: "POST", body: { details } });
    },
    postQuoteNeeded(srId, details, subtype = "customer") {
      return request(`/tech/jobs/${encodePathPart(srId)}/quote_needed`, { method: "POST", body: { details, subtype } });
    },
    postReschedule(srId, reason) {
      return request(`/tech/jobs/${encodePathPart(srId)}/reschedule`, { method: "POST", body: { reason } });
    },
    postPhotoPrepare(srId, label) {
      return request(`/tech/jobs/${encodePathPart(srId)}/photos/prepare`, { method: "POST", body: { label } });
    },
    uploadJobPhoto(srId, body) {
      return request(`/tech/jobs/${encodePathPart(srId)}/photos/upload`, { method: "POST", body });
    },
    previewCloseout(srId, body) {
      return request(`/tech/jobs/${encodePathPart(srId)}/closeout/preview`, { method: "POST", body });
    },
    submitCloseout(srId, body) {
      return request(`/tech/jobs/${encodePathPart(srId)}/closeout/submit`, { method: "POST", body });
    },
  };
}

function encodePathPart(value) {
  return encodeURIComponent(String(value || "").trim());
}

function clampTimeout(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 30000;
  return Math.min(120000, Math.max(5000, numeric));
}

export const defaultFieldDeskConfig = {
  apiBase: DEFAULT_BASE,
  apiToken: DEFAULT_TOKEN,
  technicianSubject: DEFAULT_SUBJECT,
  timeoutMs: Number(import.meta.env.VITE_OPS_HUB_API_TIMEOUT_MS || 30000),
  opsHubUrl: "",
  routeDeskUrl: "",
  partsDeskUrl: "",
};
