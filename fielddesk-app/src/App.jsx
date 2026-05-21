import { useEffect, useMemo, useRef, useState } from "react";
import BrandBar from "./components/BrandBar";
import JobList from "./components/JobList";
import JobDetailView from "./components/JobDetailView";
import SettingsView from "./components/SettingsView";
import { createFieldDeskApi, defaultFieldDeskConfig } from "./api/client";
import {
  clearNativeOfflineActions,
  enqueueNativeOfflineAction,
  getNativeHostConfig,
  getNativeBridgeSummary,
  getNativeOfflineQueueState,
  isNativeBridgeAvailable,
  openNativeExternalUrl,
  removeNativeOfflineAction,
  requestNativePushRegistration,
} from "./nativeBridge";

const STORAGE_KEY = "fielddesk-web-config";
const PREFERENCES_KEY = "fielddesk-web-preferences";
const DEFAULT_PREFERENCES = {
  activeTab: "today",
  jobFilterText: "",
  jobFilterScope: "all",
  compactQueue: false,
  lastSelectedJobId: "",
};
const TAB_ITEMS = [
  ["today", "My Day"],
  ["queue", "Queue"],
  ["job", "Job Detail"],
  ["settings", "Settings"],
];
const FILTER_SCOPES = new Set(["all", "next", "open", "parts", "done", "unscheduled"]);
const TAB_KEYS = new Set(TAB_ITEMS.map(([key]) => key));

export default function App() {
  const [config, setConfig] = useState(() => readStoredConfig());
  const [draftConfig, setDraftConfig] = useState(() => readStoredConfig());
  const [preferences, setPreferences] = useState(() => readStoredPreferences());
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [selectedJobId, setSelectedJobIdState] = useState(() => preferences.lastSelectedJobId);
  const [jobDetail, setJobDetail] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [parts, setParts] = useState(null);
  const [photos, setPhotos] = useState(null);
  const [jobLoading, setJobLoading] = useState(false);
  const [jobError, setJobError] = useState("");
  const [actionState, setActionState] = useState(null);
  const [pingState, setPingState] = useState(null);
  const [activeTab, setActiveTabState] = useState(() => normalizeTabKey(preferences.activeTab));
  const [jobFilterText, setJobFilterTextState] = useState(() => preferences.jobFilterText);
  const [jobFilterScope, setJobFilterScopeState] = useState(() => normalizeFilterScope(preferences.jobFilterScope));
  const [compactQueue, setCompactQueueState] = useState(() => Boolean(preferences.compactQueue));
  const [queueReplayState, setQueueReplayState] = useState(null);
  const [photoGallery, setPhotoGallery] = useState([]);
  const [bridgeState, setBridgeState] = useState(() => ({
    available: isNativeBridgeAvailable(),
    offlineQueue: getNativeOfflineQueueState(),
    summary: getNativeBridgeSummary(),
    pushMessage: "",
  }));
  const jobLoadSequence = useRef(0);
  const todayLoadSequence = useRef(0);
  const replaySequence = useRef(0);

  const api = useMemo(() => createFieldDeskApi(() => config), [config]);
  const selectedJob = jobs.find((job) => String(job.id) === String(selectedJobId)) || jobDetail;
  const rankedJobs = useMemo(() => jobs.map((job) => ({ ...job, queueScore: scoreJob(job), rankLabel: describeJobRank(scoreJob(job)) })), [jobs]);
  const filteredJobs = useMemo(() => {
    const query = jobFilterText.trim().toLowerCase();
    return rankedJobs.filter((job) => {
      const status = String(job.status || "").toLowerCase();
      const partsStage = String(job.partsStage || "").toLowerCase();
      const queueScore = Number(job.queueScore || 0);
      const matchesScope =
        jobFilterScope === "all" ||
        (jobFilterScope === "next" && queueScore >= 70) ||
        (jobFilterScope === "open" && !status.includes("complete")) ||
        (jobFilterScope === "done" && status.includes("complete")) ||
        (jobFilterScope === "unscheduled" && !job.appointmentWindow) ||
        (jobFilterScope === "parts" && (partsStage.includes("part") || status.includes("part")));
      if (!matchesScope) return false;
      if (!query) return true;
      return [job.id, job.customerName, job.address, job.status, job.partsStage].some((value) => String(value || "").toLowerCase().includes(query));
    });
  }, [jobFilterScope, jobFilterText, rankedJobs]);
  const workspaceLinks = useMemo(
    () =>
      [
        ["Ops Hub", config.opsHubUrl],
        ["RouteDesk", config.routeDeskUrl],
        ["PartsDesk", config.partsDeskUrl],
      ]
        .filter(([, url]) => typeof url === "string" && url.trim())
        .map(([label, url]) => ({ label, url })),
    [config.opsHubUrl, config.partsDeskUrl, config.routeDeskUrl]
  );
  const counts = {
    queue: jobs.length,
    done: jobs.filter((job) => String(job.status || "").toLowerCase().includes("complete")).length,
    pending: jobs.filter((job) => !String(job.status || "").toLowerCase().includes("complete")).length,
    parts: jobs.filter((job) => String(job.partsStage || "").toLowerCase().includes("part")).length,
    next: rankedJobs.filter((job) => (job.queueScore || 0) >= 70).length,
    unscheduled: rankedJobs.filter((job) => !job.appointmentWindow).length,
    visible: filteredJobs.length,
  };
  const groupedJobs = useMemo(() => buildJobSections(filteredJobs), [filteredJobs]);
  const queueSummary = useMemo(() => buildQueueSummary(rankedJobs, filteredJobs), [filteredJobs, rankedJobs]);

  useEffect(() => {
    document.documentElement.dataset.theme = config.themeMode || "dark";
    document.title = "FieldDesk | OpsHub";
  }, [config.themeMode]);

  useEffect(() => {
    safeLocalStorageSet(
      PREFERENCES_KEY,
      JSON.stringify({
        activeTab,
        jobFilterText,
        jobFilterScope,
        compactQueue,
        lastSelectedJobId: selectedJobId,
      })
    );
  }, [activeTab, compactQueue, jobFilterScope, jobFilterText, selectedJobId]);

  useEffect(() => {
    const nativeConfig = getNativeHostConfig();
    if (!nativeConfig) return;
    setConfig((current) => ({ ...current, ...nativeConfig }));
    setDraftConfig((current) => ({ ...current, ...nativeConfig }));
    setBridgeState({
      available: true,
      offlineQueue: getNativeOfflineQueueState(),
      summary: getNativeBridgeSummary(),
      pushMessage: "",
    });
  }, []);

  useEffect(() => {
    if (!config.apiBase || !config.apiToken || !config.technicianSubject) return;
    loadToday();
  }, [config]);

  useEffect(() => {
    if (!selectedJobId) return;
    loadJob(selectedJobId);
  }, [selectedJobId, api]);

  useEffect(() => {
    setPhotoGallery(readPhotoGallery(selectedJobId));
  }, [selectedJobId]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const onNativePhoto = async (event) => {
      const detail = event?.detail && typeof event.detail === "object" ? event.detail : null;
      if (!detail?.srId) return;
      const payload = {
        label: detail.label || "job photo",
        filename: detail.filename || `sr-${detail.srId}-photo.jpg`,
        contentType: detail.contentType || "image/jpeg",
        dataBase64: detail.dataBase64 || "",
      };
      if (!payload.dataBase64) {
        setActionState({ error: true, message: detail.message || "Native camera capture did not return photo data." });
        return;
      }
      setActionState({ loading: true, message: "Uploading native photo..." });
      try {
        const result = await api.uploadJobPhoto(detail.srId, payload);
        recordPhotoGalleryEntry(detail.srId, {
          label: payload.label,
          filename: payload.filename,
          source: "native_capture",
          status: result?.success === false ? "upload_error" : "uploaded",
          contentType: payload.contentType,
          capturedAt: new Date().toISOString(),
        });
        if (String(detail.srId) === String(selectedJobId)) {
          setPhotoGallery(readPhotoGallery(detail.srId));
        }
        setActionState({ error: !result?.success, message: result?.message || "Photo uploaded." });
      } catch (error) {
        queueOfflineAction("photo_upload", { srId: detail.srId, ...payload });
        recordPhotoGalleryEntry(detail.srId, {
          label: payload.label,
          filename: payload.filename,
          source: "native_capture",
          status: "queued",
          contentType: payload.contentType,
          capturedAt: new Date().toISOString(),
        });
        if (String(detail.srId) === String(selectedJobId)) {
          setPhotoGallery(readPhotoGallery(detail.srId));
        }
        setActionState({ error: true, message: `${formatError(error)} Photo upload was queued for replay.` });
      } finally {
        await Promise.all([loadToday(), loadJob(detail.srId)]);
      }
    };
    window.addEventListener("fielddesk:native-photo", onNativePhoto);
    return () => window.removeEventListener("fielddesk:native-photo", onNativePhoto);
  }, [api]);

  useEffect(() => {
    if (!bridgeState.available || !bridgeState.offlineQueue?.count || !config.apiBase || !config.apiToken || !config.technicianSubject) {
      return undefined;
    }
    const triggerReplay = () => {
      maybeReplayOfflineQueue("background recovery");
    };
    const timeoutId = window.setTimeout(triggerReplay, 2500);
    window.addEventListener("online", triggerReplay);
    window.addEventListener("focus", triggerReplay);
    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("online", triggerReplay);
      window.removeEventListener("focus", triggerReplay);
    };
  }, [bridgeState.available, bridgeState.offlineQueue?.count, config.apiBase, config.apiToken, config.technicianSubject]);

  async function loadToday() {
    const sequence = ++todayLoadSequence.current;
    setJobsLoading(true);
    setJobsError("");
    try {
      const payload = await api.getToday();
      const nextJobs = Array.isArray(payload) ? payload : [];
      if (sequence !== todayLoadSequence.current) return;
      setJobs(nextJobs.sort((left, right) => scoreJob(right) - scoreJob(left)));
      if (!selectedJobId && nextJobs[0]?.id) {
        setSelectedJobId(nextJobs[0].id);
      } else if (selectedJobId && !nextJobs.some((job) => String(job.id) === String(selectedJobId))) {
        setSelectedJobId(nextJobs[0]?.id || "");
      }
    } catch (error) {
      if (sequence !== todayLoadSequence.current) return;
      setJobsError(formatError(error));
    } finally {
      if (sequence !== todayLoadSequence.current) return;
      setJobsLoading(false);
    }
  }

  async function loadJob(srId) {
    setJobLoading(true);
    setJobError("");
    const sequence = ++jobLoadSequence.current;
    try {
      const [jobPayload, timelinePayload, partsPayload, photosPayload] = await Promise.allSettled([
        api.getJob(srId),
        api.getTimeline(srId),
        api.getParts(srId),
        api.getPhotos(srId),
      ]);
      if (sequence !== jobLoadSequence.current) return;
      setJobDetail(jobPayload.status === "fulfilled" ? jobPayload.value : null);
      setTimeline(timelinePayload.status === "fulfilled" ? timelinePayload.value : []);
      setParts(partsPayload.status === "fulfilled" ? partsPayload.value : null);
      setPhotos(photosPayload.status === "fulfilled" ? photosPayload.value : null);
      const errors = [jobPayload, timelinePayload, partsPayload, photosPayload]
        .filter((item) => item.status === "rejected")
        .map((item) => formatError(item.reason));
      setJobError(errors[0] || "");
    } catch (error) {
      if (sequence !== jobLoadSequence.current) return;
      setJobError(formatError(error));
    } finally {
      if (sequence !== jobLoadSequence.current) return;
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
      else if (action === "closeoutPreview") result = await api.previewCloseout(selectedJobId, payload.body);
      else if (action === "closeoutSubmit") result = await api.submitCloseout(selectedJobId, payload.body);
      else result = { success: false, message: "Unsupported action." };
      payload?.onDone?.();
      setActionState({ error: !result?.success, message: result?.message || "Action complete." });
      await Promise.all([loadToday(), loadJob(selectedJobId)]);
      return result;
    } catch (error) {
      setActionState({ error: true, message: formatError(error) });
      return null;
    }
  }

  function updateDraftConfig(key, value) {
    setDraftConfig((current) => ({ ...current, [key]: value }));
  }

  function applyConfig() {
    const sanitized = sanitizeConfig(draftConfig);
    const validationError = validateConfig(sanitized);
    if (validationError) {
      setPingState({ error: true, message: validationError });
      return;
    }
    setConfig(sanitized);
    setDraftConfig(sanitized);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sanitized));
    setPingState({ message: "FieldDesk web config saved." });
  }

  function refreshBridgeState(pushMessage = bridgeState.pushMessage) {
    setBridgeState({
      available: isNativeBridgeAvailable(),
      offlineQueue: getNativeOfflineQueueState(),
      summary: getNativeBridgeSummary(),
      pushMessage,
    });
  }

  function queueOfflineAction(actionType, payload) {
    const result = enqueueNativeOfflineAction(actionType, payload);
    refreshBridgeState(result?.message || bridgeState.pushMessage);
    return result;
  }

  function removeOfflineAction(actionId) {
    const result = removeNativeOfflineAction(actionId);
    refreshBridgeState(result?.message || bridgeState.pushMessage);
  }

  function clearOfflineQueue() {
    const result = clearNativeOfflineActions();
    refreshBridgeState(result?.message || bridgeState.pushMessage);
  }

  function requestPushBridge() {
    const result = requestNativePushRegistration();
    refreshBridgeState(result?.message || "");
  }

  async function pingApi() {
    const sanitized = sanitizeConfig(draftConfig);
    const validationError = validateConfig(sanitized);
    if (validationError) {
      setPingState({ error: true, message: validationError });
      return;
    }
    const testApi = createFieldDeskApi(() => sanitized);
    setPingState({ loading: true, message: "Checking Ops Hub..." });
    try {
      const payload = await testApi.health();
      setPingState({ error: !payload?.ok, message: payload?.ok ? "Ops Hub technician API reachable." : "Ops Hub health check returned an unexpected payload." });
    } catch (error) {
      setPingState({ error: true, message: formatError(error) });
    }
  }

  async function replayOfflineQueue() {
    const items = Array.isArray(bridgeState.offlineQueue?.items) ? bridgeState.offlineQueue.items : [];
    if (!items.length || queueReplayState?.loading) return;
    setQueueReplayState({ loading: true, message: "Replaying offline actions..." });
    let replayed = 0;
    let failed = 0;
    for (const item of items) {
      try {
        const success = await executeQueuedAction(api, item);
        if (success) {
          replayed += 1;
          removeNativeOfflineAction(item.id);
        } else {
          failed += 1;
        }
      } catch {
        failed += 1;
      }
    }
    refreshBridgeState(failed ? `${replayed} replayed, ${failed} still queued.` : `${replayed} queued action(s) replayed.`);
    setQueueReplayState({ error: failed > 0, message: failed ? `${replayed} replayed, ${failed} still queued.` : `${replayed} queued action(s) replayed.` });
    await Promise.all([loadToday(), selectedJobId ? loadJob(selectedJobId) : Promise.resolve()]);
    if (selectedJobId) {
      setPhotoGallery(readPhotoGallery(selectedJobId));
    }
  }

  async function maybeReplayOfflineQueue(reason) {
    const now = Date.now();
    if (queueReplayState?.loading) return;
    if (!bridgeState.offlineQueue?.count) return;
    if (now - replaySequence.current < 30000) return;
    replaySequence.current = now;
    setQueueReplayState({ loading: true, message: `Attempting ${reason}...` });
    await replayOfflineQueue();
  }

  return (
    <main className="app-shell">
      <BrandBar activeJob={selectedJob} counts={counts} onRefresh={loadToday} refreshDisabled={jobsLoading} />

      <nav className="tab-nav" aria-label="FieldDesk views">
        {TAB_ITEMS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={activeTab === key ? "tab-button active" : "tab-button"}
            aria-current={activeTab === key ? "page" : undefined}
            onClick={() => setActiveTab(key)}
          >
            {label}
            {getTabBadge(key, counts, bridgeState.offlineQueue?.count) && (
              <span className="tab-badge">{getTabBadge(key, counts, bridgeState.offlineQueue?.count)}</span>
            )}
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
              jobs={filteredJobs}
              groupedJobs={activeTab === "today" ? groupedJobs : null}
              compact={compactQueue}
              selectedJobId={selectedJobId}
              onSelectJob={(job) => {
                setSelectedJobId(job.id);
                setActiveTab("job");
              }}
              title={activeTab === "today" ? "My Day" : "Queue"}
              subtitle={activeTab === "today" ? "Today" : "All visible jobs"}
              totalCount={jobs.length}
              filterText={jobFilterText}
              filterScope={jobFilterScope}
              onFilterTextChange={setJobFilterText}
              onFilterScopeChange={setJobFilterScope}
              onClearFilters={clearQueueFilters}
            />
            <JobDetailView
              job={selectedJob}
              timeline={timeline}
              parts={parts}
              photos={photos}
              photoGallery={photoGallery}
              loading={jobLoading}
              error={jobError}
              actionState={actionState}
              onAction={handleAction}
              onQueueOfflineAction={queueOfflineAction}
              bridgeAvailable={bridgeState.available}
              workspaceLinks={workspaceLinks}
              onOpenWorkspaceLink={openWorkspaceLink}
            />
            <QueueSummaryPanel
              summary={queueSummary}
              counts={counts}
              compactQueue={compactQueue}
              onCompactQueueChange={setCompactQueue}
              onScopeChange={setJobFilterScope}
            />
          </>
        )}

        {activeTab === "job" && (
          <>
            <JobList
              jobs={filteredJobs}
              groupedJobs={null}
              compact={compactQueue}
              selectedJobId={selectedJobId}
              onSelectJob={(job) => setSelectedJobId(job.id)}
              title="Visible stops"
              subtitle="Queue"
              totalCount={jobs.length}
              filterText={jobFilterText}
              filterScope={jobFilterScope}
              onFilterTextChange={setJobFilterText}
              onFilterScopeChange={setJobFilterScope}
              onClearFilters={clearQueueFilters}
            />
            <JobDetailView
              job={selectedJob}
              timeline={timeline}
              parts={parts}
              photos={photos}
              photoGallery={photoGallery}
              loading={jobLoading}
              error={jobError}
              actionState={actionState}
              onAction={handleAction}
              onQueueOfflineAction={queueOfflineAction}
              bridgeAvailable={bridgeState.available}
              workspaceLinks={workspaceLinks}
              onOpenWorkspaceLink={openWorkspaceLink}
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
                <span className="queue-chip">Bridge: {bridgeState.available ? "connected" : "browser only"}</span>
                <span className="queue-chip">Offline queued: {bridgeState.offlineQueue?.count || 0}</span>
                <span className="queue-chip">Push: scaffolded</span>
                <span className="queue-chip">Parts blockers: {counts.parts}</span>
              </div>
              <div className="detail-grid">
                {Object.entries(bridgeState.summary || {}).map(([key, ready]) => (
                  <div key={key} className="detail-value">
                    <span>{formatBridgeCapability(key)}</span>
                    <strong>{ready ? "Ready" : "Unavailable"}</strong>
                  </div>
                ))}
              </div>
              <div className="action-row">
                <button type="button" onClick={requestPushBridge}>Request push bridge</button>
                <button type="button" className="secondary-button" onClick={() => refreshBridgeState()}>Refresh bridge state</button>
              </div>
              {bridgeState.pushMessage && <p className="muted">{bridgeState.pushMessage}</p>}
            </section>
          </>
        )}
      </div>

      {jobsError && <p className="error-text">{jobsError}</p>}
      {jobsLoading && <p className="muted">Loading technician queue…</p>}
      {bridgeState.offlineQueue?.count > 0 && (
        <section className="panel stack-gap">
          <p className="section-kicker">Offline Queue</p>
          <strong>{bridgeState.offlineQueue.count} action(s) are staged in the Android host.</strong>
          <div className="history-list">
            {(bridgeState.offlineQueue.items || []).slice(0, 5).map((item) => (
              <div key={item.id || `${item.actionType}-${item.createdAtEpochMillis}`} className="history-entry compact-entry">
                <div className="detail-head">
                  <p>{item.actionType}</p>
                  <button type="button" className="secondary-button" onClick={() => removeOfflineAction(item.id)}>Remove</button>
                </div>
                <span>{new Date(item.createdAtEpochMillis).toLocaleString()}</span>
              </div>
            ))}
          </div>
          <div className="action-row">
            <button type="button" className="secondary-button" onClick={() => queueOfflineAction("fielddesk_refresh", { selectedJobId })}>
              Queue refresh marker
            </button>
            <button type="button" className="secondary-button" onClick={replayOfflineQueue}>
              Replay queue
            </button>
            <button type="button" className="secondary-button" onClick={clearOfflineQueue}>
              Clear queue
            </button>
            <button type="button" className="secondary-button" onClick={() => refreshBridgeState()}>
              Refresh queue state
            </button>
          </div>
          {queueReplayState?.message && <p className={queueReplayState.error ? "error-text" : "muted"}>{queueReplayState.message}</p>}
        </section>
      )}
    </main>
  );

  function openWorkspaceLink(url) {
    if (!isHttpUrl(url)) {
      setPingState({ error: true, message: "Workspace link must start with http:// or https://." });
      return;
    }
    const nativeResult = openNativeExternalUrl(url);
    if (nativeResult?.success || nativeResult?.available) {
      setPingState({ error: !nativeResult.success, message: nativeResult.message || "Opening workspace..." });
      return;
    }
    if (typeof window !== "undefined") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
  }

  function setActiveTab(value) {
    const nextValue = normalizeTabKey(value);
    setActiveTabState(nextValue);
    setPreferences((current) => ({ ...current, activeTab: nextValue }));
  }

  function setJobFilterText(value) {
    const nextValue = String(value || "").slice(0, 120);
    setJobFilterTextState(nextValue);
    setPreferences((current) => ({ ...current, jobFilterText: nextValue }));
  }

  function setJobFilterScope(value) {
    const nextValue = normalizeFilterScope(value);
    setJobFilterScopeState(nextValue);
    setPreferences((current) => ({ ...current, jobFilterScope: nextValue }));
  }

  function setCompactQueue(value) {
    const nextValue = Boolean(value);
    setCompactQueueState(nextValue);
    setPreferences((current) => ({ ...current, compactQueue: nextValue }));
  }

  function clearQueueFilters() {
    setJobFilterText("");
    setJobFilterScope("all");
  }

  function setSelectedJobId(value) {
    const nextValue = normalizeIdentifier(value);
    setSelectedJobIdState(nextValue);
    setPreferences((current) => ({ ...current, lastSelectedJobId: nextValue }));
  }
}

function readStoredConfig() {
  if (typeof window === "undefined") return { ...defaultFieldDeskConfig, themeMode: "dark" };
  try {
    const parsed = JSON.parse(safeLocalStorageGet(STORAGE_KEY) || "{}");
    return {
      ...sanitizeConfig(defaultFieldDeskConfig),
      themeMode: "dark",
      ...sanitizeConfig(parsed),
      ...(getNativeHostConfig() || {}),
    };
  } catch {
    return { ...defaultFieldDeskConfig, themeMode: "dark" };
  }
}

function readStoredPreferences() {
  if (typeof window === "undefined") return { ...DEFAULT_PREFERENCES };
  try {
    const parsed = JSON.parse(safeLocalStorageGet(PREFERENCES_KEY) || "{}");
    return {
      ...DEFAULT_PREFERENCES,
      ...parsed,
      activeTab: normalizeTabKey(parsed.activeTab),
      jobFilterText: String(parsed.jobFilterText || "").slice(0, 120),
      jobFilterScope: normalizeFilterScope(parsed.jobFilterScope),
      compactQueue: Boolean(parsed.compactQueue),
      lastSelectedJobId: normalizeIdentifier(parsed.lastSelectedJobId),
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

function formatError(error) {
  return error instanceof Error ? error.message : String(error || "Unknown error");
}

function formatBridgeCapability(value) {
  return String(value || "")
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (letter) => letter.toUpperCase());
}

function sanitizeConfig(raw) {
  const themeMode = ["dark", "light"].includes(raw?.themeMode) ? raw.themeMode : "dark";
  const timeoutMs = clampNumber(raw?.timeoutMs || defaultFieldDeskConfig.timeoutMs, 5000, 120000);
  return {
    ...defaultFieldDeskConfig,
    ...(raw || {}),
    apiBase: normalizeUrl(raw?.apiBase || defaultFieldDeskConfig.apiBase),
    apiToken: String(raw?.apiToken || "").trim(),
    technicianSubject: String(raw?.technicianSubject || "").trim(),
    timeoutMs,
    themeMode,
    opsHubUrl: normalizeOptionalUrl(raw?.opsHubUrl),
    routeDeskUrl: normalizeOptionalUrl(raw?.routeDeskUrl),
    partsDeskUrl: normalizeOptionalUrl(raw?.partsDeskUrl),
  };
}

function validateConfig(config) {
  if (!config.apiBase) return "Ops Hub API base is required.";
  if (!/^https?:\/\//i.test(config.apiBase)) return "Ops Hub API base must start with http:// or https://.";
  if (!config.apiToken) return "Technician API token is required.";
  if (!config.technicianSubject) return "Technician subject is required.";
  return "";
}

function normalizeUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function normalizeOptionalUrl(value) {
  const normalized = normalizeUrl(value);
  return /^https?:\/\//i.test(normalized) ? normalized : "";
}

function normalizeTabKey(value) {
  return TAB_KEYS.has(value) ? value : DEFAULT_PREFERENCES.activeTab;
}

function normalizeFilterScope(value) {
  return FILTER_SCOPES.has(value) ? value : DEFAULT_PREFERENCES.jobFilterScope;
}

function normalizeIdentifier(value) {
  return String(value || "").trim().slice(0, 80);
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || "").trim());
}

function clampNumber(value, min, max) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return min;
  return Math.min(max, Math.max(min, numeric));
}

function safeLocalStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return "";
  }
}

function safeLocalStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage is best effort for technician preferences.
  }
}

function scoreJob(job) {
  const status = String(job?.status || "").toLowerCase();
  const partsStage = String(job?.partsStage || "").toLowerCase();
  let score = 0;
  if (!status.includes("complete")) score += 40;
  if (job?.appointmentWindow) score += 20;
  if (partsStage && !partsStage.includes("none") && !partsStage.includes("received")) score -= 20;
  if (status.includes("arrive") || status.includes("en route") || status.includes("start")) score += 30;
  if (status.includes("scheduled")) score += 15;
  return score;
}

function describeJobRank(score) {
  if (score >= 70) return "Next best stop";
  if (score >= 45) return "Ready today";
  if (score >= 20) return "Watch list";
  return "Blocked";
}

function buildJobSections(items) {
  const sections = [
    { label: "Next best stops", items: items.filter((item) => (item.queueScore || 0) >= 70) },
    { label: "Ready today", items: items.filter((item) => (item.queueScore || 0) >= 45 && (item.queueScore || 0) < 70) },
    { label: "Needs follow-up", items: items.filter((item) => (item.queueScore || 0) < 45) },
  ];
  return sections.filter((section) => section.items.length > 0);
}

function buildQueueSummary(rankedJobs, filteredJobs) {
  const nextJob = rankedJobs[0] || null;
  const visibleTop = filteredJobs[0] || null;
  return {
    nextJob,
    visibleTop,
    hasFilteredView: Boolean(filteredJobs.length && nextJob && visibleTop && String(nextJob.id) !== String(visibleTop.id)),
    blockers: rankedJobs.filter((job) => (job.queueScore || 0) < 20),
  };
}

function getTabBadge(key, counts, offlineCount = 0) {
  if (key === "today") return counts.next ? String(counts.next) : "";
  if (key === "queue") return counts.pending ? String(counts.pending) : "";
  if (key === "job") return counts.parts ? String(counts.parts) : "";
  if (key === "settings") return offlineCount ? String(offlineCount) : "";
  return "";
}

function QueueSummaryPanel({ summary, counts, compactQueue, onCompactQueueChange, onScopeChange }) {
  return (
    <section className="panel stack-gap queue-summary-panel">
      <div className="section-head">
        <div>
          <p className="section-kicker">Shift Pulse</p>
          <h2>Queue posture</h2>
        </div>
      </div>
      <div className="detail-grid">
        <div className="detail-value">
          <span>Next stop</span>
          <strong>{summary.nextJob?.customerName || summary.nextJob?.id || "No loaded stop"}</strong>
        </div>
        <div className="detail-value">
          <span>Visible top</span>
          <strong>{summary.visibleTop?.id ? `SR-${summary.visibleTop.id}` : "No visible stop"}</strong>
        </div>
        <div className="detail-value">
          <span>Parts blockers</span>
          <strong>{counts.parts}</strong>
        </div>
        <div className="detail-value">
          <span>Unscheduled</span>
          <strong>{counts.unscheduled}</strong>
        </div>
        <div className="detail-value">
          <span>Blocked</span>
          <strong>{summary.blockers.length}</strong>
        </div>
      </div>
      {summary.hasFilteredView && <p className="muted">The current filter is hiding the highest ranked stop.</p>}
      <div className="action-row">
        <label className="checkbox-row queue-toggle">
          <input type="checkbox" checked={compactQueue} onChange={(event) => onCompactQueueChange(event.target.checked)} />
          <span>Compact queue</span>
        </label>
        <button type="button" className="secondary-button" onClick={() => onScopeChange("parts")}>
          Show parts blockers
        </button>
        <button type="button" className="secondary-button" onClick={() => onScopeChange("next")}>
          Show next stops
        </button>
        <button type="button" className="secondary-button" onClick={() => onScopeChange("unscheduled")}>
          Show unscheduled
        </button>
        <button type="button" className="secondary-button" onClick={() => onScopeChange("all")}>
          Show all
        </button>
      </div>
    </section>
  );
}

async function executeQueuedAction(api, item) {
  const payload = parseQueuedPayload(item?.payload);
  const srId = payload?.srId || item?.srId;
  if (item?.actionType === "fielddesk_refresh") return true;
  if (!srId) return false;
  if (item?.actionType === "photo_prepare") {
    await api.postPhotoPrepare(srId, payload.label || "before");
    return true;
  }
  if (item?.actionType === "photo_upload") {
    await api.uploadJobPhoto(srId, {
      label: payload.label,
      filename: payload.filename,
      contentType: payload.contentType,
      dataBase64: payload.dataBase64,
    });
    recordPhotoGalleryStatus(srId, payload.filename, "uploaded");
    return true;
  }
  if (item?.actionType === "closeout_submit") {
    const { srId: _, ...body } = payload;
    await api.submitCloseout(srId, body);
    return true;
  }
  if (item?.actionType === "note") {
    await api.postNote(srId, payload.note || "");
    return true;
  }
  if (item?.actionType === "status") {
    await api.postStatus(srId, payload.status || "");
    return true;
  }
  if (item?.actionType === "parts") {
    await api.postParts(srId, payload.details || "");
    return true;
  }
  if (item?.actionType === "quote_needed") {
    await api.postQuoteNeeded(srId, payload.details || "", payload.subtype || "customer");
    return true;
  }
  if (item?.actionType === "reschedule") {
    await api.postReschedule(srId, payload.reason || "");
    return true;
  }
  return false;
}

function photoGalleryKey(jobId) {
  return `fielddesk-photo-gallery-${jobId}`;
}

function readPhotoGallery(jobId) {
  if (typeof window === "undefined" || !jobId) return [];
  try {
    const raw = window.localStorage.getItem(photoGalleryKey(jobId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistPhotoGallery(jobId, items) {
  if (typeof window === "undefined" || !jobId) return;
  window.localStorage.setItem(photoGalleryKey(jobId), JSON.stringify(items.slice(0, 20)));
}

function recordPhotoGalleryEntry(jobId, entry) {
  if (!jobId) return;
  const current = readPhotoGallery(jobId);
  const deduped = current.filter((item) => item.filename !== entry.filename);
  persistPhotoGallery(jobId, [{ ...entry }, ...deduped]);
}

function recordPhotoGalleryStatus(jobId, filename, status) {
  if (!jobId || !filename) return;
  const current = readPhotoGallery(jobId);
  persistPhotoGallery(
    jobId,
    current.map((item) => (item.filename === filename ? { ...item, status, syncedAt: new Date().toISOString() } : item))
  );
}

function parseQueuedPayload(raw) {
  if (!raw) return {};
  if (typeof raw === "object") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return String(raw)
      .split("&")
      .reduce((accumulator, pair) => {
        const [key, value] = pair.split("=");
        if (!key) return accumulator;
        accumulator[key] = decodeURIComponent(value || "");
        return accumulator;
      }, {});
  }
}
