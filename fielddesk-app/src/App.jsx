import { useEffect, useMemo, useState } from "react";
import BrandBar from "./components/BrandBar";
import JobList from "./components/JobList";
import JobDetailView from "./components/JobDetailView";
import SettingsView from "./components/SettingsView";
import { createFieldDeskApi, defaultFieldDeskConfig } from "./api/client";

const STORAGE_KEY = "fielddesk-web-config";

export default function App() {
  const [config, setConfig] = useState(() => readStoredConfig());
  const [draftConfig, setDraftConfig] = useState(() => readStoredConfig());
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [selectedJobId, setSelectedJobId] = useState("");
  const [jobDetail, setJobDetail] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [parts, setParts] = useState(null);
  const [photos, setPhotos] = useState(null);
  const [jobLoading, setJobLoading] = useState(false);
  const [jobError, setJobError] = useState("");
  const [actionState, setActionState] = useState(null);
  const [pingState, setPingState] = useState(null);
  const [activeTab, setActiveTab] = useState("today");

  const api = useMemo(() => createFieldDeskApi(() => config), [config]);
  const selectedJob = jobs.find((job) => String(job.id) === String(selectedJobId)) || jobDetail;
  const counts = {
    queue: jobs.length,
    done: jobs.filter((job) => String(job.status || "").toLowerCase().includes("complete")).length,
    pending: jobs.filter((job) => !String(job.status || "").toLowerCase().includes("complete")).length,
  };

  useEffect(() => {
    document.documentElement.dataset.theme = config.themeMode || "dark";
    document.title = "FieldDesk | OpsHub";
  }, [config.themeMode]);

  useEffect(() => {
    if (!config.apiBase || !config.apiToken || !config.technicianSubject) return;
    loadToday();
  }, [config]);

  useEffect(() => {
    if (!selectedJobId) return;
    loadJob(selectedJobId);
  }, [selectedJobId, api]);

  async function loadToday() {
    setJobsLoading(true);
    setJobsError("");
    try {
      const payload = await api.getToday();
      setJobs(Array.isArray(payload) ? payload : []);
      if (!selectedJobId && Array.isArray(payload) && payload[0]?.id) {
        setSelectedJobId(String(payload[0].id));
      }
    } catch (error) {
      setJobsError(formatError(error));
    } finally {
      setJobsLoading(false);
    }
  }

  async function loadJob(srId) {
    setJobLoading(true);
    setJobError("");
    try {
      const [jobPayload, timelinePayload, partsPayload, photosPayload] = await Promise.allSettled([
        api.getJob(srId),
        api.getTimeline(srId),
        api.getParts(srId),
        api.getPhotos(srId),
      ]);
      setJobDetail(jobPayload.status === "fulfilled" ? jobPayload.value : null);
      setTimeline(timelinePayload.status === "fulfilled" ? timelinePayload.value : []);
      setParts(partsPayload.status === "fulfilled" ? partsPayload.value : null);
      setPhotos(photosPayload.status === "fulfilled" ? photosPayload.value : null);
      const errors = [jobPayload, timelinePayload, partsPayload, photosPayload]
        .filter((item) => item.status === "rejected")
        .map((item) => formatError(item.reason));
      setJobError(errors[0] || "");
    } finally {
      setJobLoading(false);
    }
  }

  async function handleAction(action, payload) {
    if (!selectedJobId) return;
    setActionState({ loading: true, message: "Running technician update..." });
    try {
      let result;
      if (action === "status") result = await api.postStatus(selectedJobId, payload.status);
      else if (action === "callAhead") result = await api.postCallAhead(selectedJobId, payload.minutes);
      else if (action === "note") result = await api.postNote(selectedJobId, payload.note);
      else if (action === "parts") result = await api.postParts(selectedJobId, payload.details);
      else if (action === "quoteNeeded") result = await api.postQuoteNeeded(selectedJobId, payload.details);
      else if (action === "reschedule") result = await api.postReschedule(selectedJobId, payload.reason);
      else if (action === "photoPrepare") result = await api.postPhotoPrepare(selectedJobId, payload.label);
      else result = { success: false, message: "Unsupported action." };
      payload?.onDone?.();
      setActionState({ error: !result?.success, message: result?.message || "Action complete." });
      await Promise.all([loadToday(), loadJob(selectedJobId)]);
    } catch (error) {
      setActionState({ error: true, message: formatError(error) });
    }
  }

  function updateDraftConfig(key, value) {
    setDraftConfig((current) => ({ ...current, [key]: value }));
  }

  function applyConfig() {
    setConfig(draftConfig);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draftConfig));
    setPingState({ message: "FieldDesk web config saved." });
  }

  async function pingApi() {
    const testApi = createFieldDeskApi(() => draftConfig);
    setPingState({ loading: true, message: "Checking Ops Hub..." });
    try {
      const payload = await testApi.health();
      setPingState({ error: !payload?.ok, message: payload?.ok ? "Ops Hub technician API reachable." : "Ops Hub health check returned an unexpected payload." });
    } catch (error) {
      setPingState({ error: true, message: formatError(error) });
    }
  }

  return (
    <main className="app-shell">
      <BrandBar activeJob={selectedJob} counts={counts} onRefresh={loadToday} refreshDisabled={jobsLoading} />

      <nav className="tab-nav">
        {[
          ["today", "My Day"],
          ["queue", "Queue"],
          ["job", "Job Detail"],
          ["settings", "Settings"],
        ].map(([key, label]) => (
          <button key={key} type="button" className={activeTab === key ? "tab-button active" : "tab-button"} onClick={() => setActiveTab(key)}>
            {label}
          </button>
        ))}
      </nav>

      {(!config.apiBase || !config.apiToken || !config.technicianSubject) && (
        <section className="panel stack-gap">
          <p className="section-kicker">Setup Required</p>
          <strong>FieldDesk web needs Ops Hub settings before it can resolve a technician.</strong>
          <p className="muted">Enter the technician API base, token, and technician subject in Settings. This is the same config an Android wrapper should persist locally.</p>
        </section>
      )}

      <div className="layout-grid">
        {(activeTab === "today" || activeTab === "queue") && (
          <>
            <JobList
              jobs={jobs}
              selectedJobId={selectedJobId}
              onSelectJob={(job) => {
                setSelectedJobId(String(job.id));
                setActiveTab("job");
              }}
              title={activeTab === "today" ? "My Day" : "Queue"}
              subtitle={activeTab === "today" ? "Today" : "All visible jobs"}
            />
            <JobDetailView
              job={selectedJob}
              timeline={timeline}
              parts={parts}
              photos={photos}
              loading={jobLoading}
              error={jobError}
              actionState={actionState}
              onAction={handleAction}
            />
          </>
        )}

        {activeTab === "job" && (
          <>
            <JobList
              jobs={jobs}
              selectedJobId={selectedJobId}
              onSelectJob={(job) => setSelectedJobId(String(job.id))}
              title="Visible stops"
              subtitle="Queue"
            />
            <JobDetailView
              job={selectedJob}
              timeline={timeline}
              parts={parts}
              photos={photos}
              loading={jobLoading}
              error={jobError}
              actionState={actionState}
              onAction={handleAction}
            />
          </>
        )}

        {activeTab === "settings" && (
          <>
            <SettingsView config={draftConfig} onChange={updateDraftConfig} onApply={applyConfig} onPing={pingApi} pingState={pingState} />
            <section className="panel stack-gap">
              <div className="section-head">
                <div>
                  <p className="section-kicker">Wrapper Direction</p>
                  <h2>Android host</h2>
                </div>
              </div>
              <p className="muted">
                The Android app should persist these values and host this web frontend in a thin wrapper. UI and workflow changes then ship through the frontend instead of requiring a native rewrite for every field change.
              </p>
              <div className="chip-list">
                <span className="queue-chip">Native bridge later: camera</span>
                <span className="queue-chip">Native bridge later: offline cache</span>
                <span className="queue-chip">Native bridge later: push</span>
              </div>
            </section>
          </>
        )}
      </div>

      {jobsError && <p className="error-text">{jobsError}</p>}
      {jobsLoading && <p className="muted">Loading technician queue…</p>}
    </main>
  );
}

function readStoredConfig() {
  if (typeof window === "undefined") return { ...defaultFieldDeskConfig, themeMode: "dark" };
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return {
      ...defaultFieldDeskConfig,
      themeMode: "dark",
      ...parsed,
    };
  } catch {
    return { ...defaultFieldDeskConfig, themeMode: "dark" };
  }
}

function formatError(error) {
  return error instanceof Error ? error.message : String(error || "Unknown error");
}
