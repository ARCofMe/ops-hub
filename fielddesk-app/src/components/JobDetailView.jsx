import { useEffect, useMemo, useState } from "react";
import { captureNativePhoto, openNativeNavigation, requestNativeLocation } from "../nativeBridge";

const STATUS_ACTIONS = [
  ["En route", "enroute"],
  ["Arrived", "arrive"],
  ["Start", "start"],
  ["Complete", "complete"],
];

export default function JobDetailView({
  job,
  timeline,
  parts,
  photos,
  loading,
  error,
  actionState,
  onAction,
  onQueueOfflineAction,
  bridgeAvailable,
  workspaceLinks,
  onOpenWorkspaceLink,
}) {
  const [note, setNote] = useState("");
  const [partsNeed, setPartsNeed] = useState("");
  const [quoteNeed, setQuoteNeed] = useState("");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [photoLabel, setPhotoLabel] = useState("before");
  const [closeoutDraft, setCloseoutDraft] = useState(defaultCloseoutDraft);
  const [closeoutPreview, setCloseoutPreview] = useState(null);
  const [bridgeMessage, setBridgeMessage] = useState("");

  const sortedTimeline = useMemo(
    () => [...(timeline || [])].sort((left, right) => String(right.occurredAt || "").localeCompare(String(left.occurredAt || ""))),
    [timeline]
  );
  const workflowSummary = useMemo(() => buildWorkflowSummary(job, parts, photos, timeline), [job, parts, photos, timeline]);

  useEffect(() => {
    if (!job?.id) return;
    setCloseoutDraft(readCloseoutDraft(job.id) || defaultCloseoutDraft());
    setCloseoutPreview(null);
  }, [job?.id]);

  useEffect(() => {
    if (!job?.id) return;
    persistCloseoutDraft(job.id, closeoutDraft);
  }, [job?.id, closeoutDraft]);

  if (!job) {
    return (
      <section className="panel stack-gap">
        <p className="section-kicker">Job Detail</p>
        <strong>Pick a stop from My Day or Queue.</strong>
        <p className="muted">FieldDesk should always open into a usable next-stop surface, not an empty mobile shell.</p>
      </section>
    );
  }

  return (
    <section className="panel stack-gap">
      <div className="section-head">
        <div>
          <p className="section-kicker">Active Job</p>
          <h2>{job.customerName || `SR-${job.id}`}</h2>
        </div>
        <span className="status-pill">{job.status || "unknown"}</span>
      </div>

      {error && <p className="error-text">{error}</p>}
      {loading && <p className="muted">Loading job context…</p>}

      <div className="detail-grid">
        <Detail label="SR" value={job.id} />
        <Detail label="Window" value={job.appointmentWindow || "Unscheduled"} />
        <Detail label="Phone" value={job.customerPhone || "n/a"} />
        <Detail label="Parts" value={parts?.stageLabel || job.partsStage || "none"} />
      </div>

      <div className="chip-list">
        <span className="queue-chip">Next action: {parts?.nextAction || job.nextAction || "Review on site"}</span>
        <span className="queue-chip">Photo mailbox: {photos?.mailboxStatus || "unknown"}</span>
        <span className="queue-chip">Timeline events: {(timeline || []).length}</span>
        <span className="queue-chip">Workflow: {workflowSummary.statusLabel}</span>
      </div>

      <div className="detail-block">
        <strong>Workflow guidance</strong>
        <div className="chip-list">
          {workflowSummary.highlights.map((item) => (
            <span key={item} className="queue-chip">{item}</span>
          ))}
        </div>
        <div className="history-list compact-list">
          {workflowSummary.checklist.map((item) => (
            <div key={item.label} className="history-entry compact-entry">
              <p>{item.label}</p>
              <span>{item.ready ? "Ready" : "Needs attention"}</span>
              {item.reason && <small>{item.reason}</small>}
            </div>
          ))}
        </div>
      </div>

      <div className="detail-block">
        <strong>Customer and stop</strong>
        <p>{job.address || "Address unavailable"}</p>
        <p className="muted">{describeStatusMeta(job.statusMeta)}</p>
        <div className="action-row">
          <button type="button" className="secondary-button" disabled={!bridgeAvailable || !job.address} onClick={() => setBridgeMessage(openNativeNavigation(job.address).message)}>
            Open native navigation
          </button>
          <button type="button" className="secondary-button" disabled={!bridgeAvailable} onClick={() => setBridgeMessage(requestNativeLocation().message)}>
            Request device location
          </button>
          <a className={job.customerPhone ? "link-button" : "link-button disabled"} href={job.customerPhone ? `tel:${sanitizePhone(job.customerPhone)}` : undefined}>
            Call customer
          </a>
        </div>
      </div>

      {workspaceLinks?.length > 0 && (
        <div className="detail-block">
          <strong>Workspace links</strong>
          <div className="action-row">
            {workspaceLinks.map((link) => (
              <button key={link.label} type="button" className="secondary-button" onClick={() => onOpenWorkspaceLink?.(link.url)}>
                Open {link.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="action-grid">
        {STATUS_ACTIONS.map(([label, value]) => (
          <button key={value} type="button" disabled={actionState?.loading} onClick={() => onAction("status", { status: value })}>
            {label}
          </button>
        ))}
        <button type="button" className="secondary-button" disabled={actionState?.loading} onClick={() => onAction("callAhead", { minutes: 30 })}>
          Call ahead +30
        </button>
      </div>

      <div className="detail-block">
        <strong>Field updates</strong>
        <label className="field">
          <span>Job note</span>
          <textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Work performed, diagnostic findings, customer communication" />
        </label>
        <div className="action-row">
          <button type="button" disabled={actionState?.loading || !note.trim()} onClick={() => onAction("note", { note, onDone: () => setNote("") })}>
            Send note
          </button>
        </div>
      </div>

      <div className="detail-block">
        <strong>Parts and office handoffs</strong>
        <label className="field">
          <span>Need parts</span>
          <input value={partsNeed} onChange={(event) => setPartsNeed(event.target.value)} placeholder="Example: evaporator fan motor open" />
        </label>
        <div className="action-row">
          <button type="button" disabled={actionState?.loading || !partsNeed.trim()} onClick={() => onAction("parts", { details: partsNeed, onDone: () => setPartsNeed("") })}>
            Send parts request
          </button>
        </div>
        <label className="field">
          <span>Quote needed</span>
          <input value={quoteNeed} onChange={(event) => setQuoteNeed(event.target.value)} placeholder="Example: sealed system repair needs approval" />
        </label>
        <div className="action-row">
          <button type="button" className="secondary-button" disabled={actionState?.loading || !quoteNeed.trim()} onClick={() => onAction("quoteNeeded", { details: quoteNeed, onDone: () => setQuoteNeed("") })}>
            Hand off quote
          </button>
        </div>
        <label className="field">
          <span>Reschedule reason</span>
          <input value={rescheduleReason} onChange={(event) => setRescheduleReason(event.target.value)} placeholder="Example: customer requested next week" />
        </label>
        <div className="action-row">
          <button type="button" className="secondary-button" disabled={actionState?.loading || !rescheduleReason.trim()} onClick={() => onAction("reschedule", { reason: rescheduleReason, onDone: () => setRescheduleReason("") })}>
            Send reschedule handoff
          </button>
        </div>
      </div>

      <div className="detail-block">
        <strong>Photo prep</strong>
        <label className="field">
          <span>Photo label</span>
          <select value={photoLabel} onChange={(event) => setPhotoLabel(event.target.value)}>
            <option value="before">Before</option>
            <option value="data_tag">Data tag</option>
            <option value="after">After</option>
            <option value="damaged_part">Damaged part</option>
          </select>
        </label>
        <div className="action-row">
          <button type="button" disabled={actionState?.loading} onClick={() => onAction("photoPrepare", { label: photoLabel })}>
            Prepare photo handoff
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={actionState?.loading || !bridgeAvailable}
            onClick={() => setBridgeMessage(captureNativePhoto(photoLabel, job.id).message)}
          >
            Capture photo (native)
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={actionState?.loading}
            onClick={() =>
              setBridgeMessage(
                onQueueOfflineAction?.("photo_prepare", { srId: job.id, label: photoLabel })?.message || "Queued photo prep."
              )
            }
          >
            Queue offline photo step
          </button>
        </div>
        <div className="chip-list">
          <span className="queue-chip">Found: {formatList(photos?.foundTags)}</span>
          <span className="queue-chip">Missing: {formatList(photos?.missingTags)}</span>
          <span className="queue-chip">Bridge: {bridgeAvailable ? "available" : "browser only"}</span>
        </div>
      </div>

      <div className="detail-block">
        <strong>Closeout</strong>
        <label className="field">
          <span>Labor code</span>
          <input
            value={closeoutDraft.laborCode}
            onChange={(event) => setCloseoutDraft((current) => ({ ...current, laborCode: event.target.value }))}
            placeholder="diagnostic"
          />
        </label>
        <label className="field">
          <span>Work performed</span>
          <textarea
            rows={4}
            value={closeoutDraft.workPerformed}
            onChange={(event) => setCloseoutDraft((current) => ({ ...current, workPerformed: event.target.value }))}
            placeholder="Describe diagnostic findings, repair performed, and final condition"
          />
        </label>
        <div className="detail-grid">
          <label className="field">
            <span>Duration minutes</span>
            <input
              type="number"
              min="1"
              value={closeoutDraft.durationMinutes}
              onChange={(event) => setCloseoutDraft((current) => ({ ...current, durationMinutes: Number(event.target.value || 0) }))}
            />
          </label>
          <label className="field">
            <span>Signed by</span>
            <input
              value={closeoutDraft.signedBy}
              onChange={(event) => setCloseoutDraft((current) => ({ ...current, signedBy: event.target.value }))}
              placeholder="Customer name"
            />
          </label>
        </div>
        <label className="field">
          <span>Outcome note</span>
          <input
            value={closeoutDraft.outcomeNote}
            onChange={(event) => setCloseoutDraft((current) => ({ ...current, outcomeNote: event.target.value }))}
            placeholder="Optional completion or follow-up note"
          />
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={closeoutDraft.customerApproved}
            onChange={(event) => setCloseoutDraft((current) => ({ ...current, customerApproved: event.target.checked }))}
          />
          <span>Customer approved work</span>
        </label>
        <div className="action-row">
          <button
            type="button"
            disabled={actionState?.loading || !closeoutDraft.workPerformed.trim()}
            onClick={async () => {
              const result = await onAction("closeoutPreview", { body: buildCloseoutPayload(closeoutDraft) });
              setCloseoutPreview(result || null);
            }}
          >
            Preview closeout
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={actionState?.loading || !closeoutDraft.workPerformed.trim()}
            onClick={() => onAction("closeoutSubmit", { body: buildCloseoutPayload(closeoutDraft) })}
          >
            Submit closeout
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() =>
              setBridgeMessage(
                onQueueOfflineAction?.("closeout_submit", { srId: job.id, ...buildCloseoutPayload(closeoutDraft) })?.message || "Queued closeout."
              )
            }
          >
            Queue offline closeout
          </button>
        </div>
        {closeoutPreview && (
          <div className="chip-list">
            <span className="queue-chip">Preview labor: {closeoutPreview.laborCode || closeoutDraft.laborCode}</span>
            <span className="queue-chip">Duration: {closeoutPreview.durationLabel || `${closeoutDraft.durationMinutes} min`}</span>
            <span className="queue-chip">Billable: {String(closeoutPreview.billable)}</span>
          </div>
        )}
        <div className="action-row">
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              const next = defaultCloseoutDraft();
              setCloseoutDraft(next);
              persistCloseoutDraft(job.id, next);
              setCloseoutPreview(null);
            }}
          >
            Reset draft
          </button>
          <span className="muted">Closeout draft is saved locally per SR.</span>
        </div>
      </div>

      {actionState?.message && <p className={actionState.error ? "error-text" : "muted"}>{actionState.message}</p>}
      {bridgeMessage && <p className="muted">{bridgeMessage}</p>}

      <details className="disclosure-card" open>
        <summary>Parts context</summary>
        <div className="detail-grid">
          <Detail label="Stage" value={parts?.stageLabel || "none"} />
          <Detail label="Status" value={parts?.status || "n/a"} />
          <Detail label="Blocker" value={parts?.blocker || "none"} />
          <Detail label="Updated" value={parts?.updatedAt || "unknown"} />
        </div>
      </details>

      <details className="disclosure-card">
        <summary>Timeline</summary>
        <div className="history-list">
          {sortedTimeline.map((entry, index) => (
            <div key={`${entry.occurredAt}-${index}`} className="history-entry">
              <p>{entry.summary}</p>
              <span>{[entry.occurredAt, entry.actorLabel, entry.source].filter(Boolean).join(" • ")}</span>
              {entry.details && <small>{entry.details}</small>}
            </div>
          ))}
          {!sortedTimeline.length && <p className="muted">No timeline entries loaded yet.</p>}
        </div>
      </details>
    </section>
  );
}

function defaultCloseoutDraft() {
  return {
    laborCode: "diagnostic",
    workPerformed: "",
    durationMinutes: 60,
    signedBy: "",
    customerApproved: false,
    finalOutcome: "completed",
    outcomeNote: "",
  };
}

function Detail({ label, value }) {
  return (
    <div className="detail-value">
      <span>{label}</span>
      <strong>{value || "n/a"}</strong>
    </div>
  );
}

function formatList(items) {
  return Array.isArray(items) && items.length ? items.join(", ") : "none";
}

function buildCloseoutPayload(draft) {
  return {
    laborCode: draft.laborCode,
    workPerformed: draft.workPerformed,
    durationMinutes: Number(draft.durationMinutes || 0) || 60,
    signedBy: draft.signedBy || null,
    customerApproved: Boolean(draft.customerApproved),
    finalOutcome: draft.finalOutcome || "completed",
    outcomeNote: draft.outcomeNote || null,
  };
}

function buildWorkflowSummary(job, parts, photos, timeline) {
  const checklist = [
    {
      label: "Customer reached",
      ready: Boolean(job?.customerPhone),
      reason: job?.customerPhone ? "Phone number is available." : "Customer phone is missing from the job payload.",
    },
    {
      label: "Parts path understood",
      ready: !parts?.blocker,
      reason: parts?.blocker || parts?.nextAction || "No active parts blocker is loaded.",
    },
    {
      label: "Photo coverage ready",
      ready: !Array.isArray(photos?.missingTags) || photos.missingTags.length === 0,
      reason: Array.isArray(photos?.missingTags) && photos.missingTags.length ? `Missing: ${photos.missingTags.join(", ")}` : "Current photo checklist is complete.",
    },
    {
      label: "Activity history present",
      ready: Array.isArray(timeline) && timeline.length > 0,
      reason: Array.isArray(timeline) && timeline.length > 0 ? "Timeline context is loaded." : "No timeline events were returned.",
    },
  ];
  const blockers = checklist.filter((item) => !item.ready);
  return {
    statusLabel: blockers.length ? `${blockers.length} blocker${blockers.length === 1 ? "" : "s"}` : "Ready to progress",
    highlights: [
      job?.status || "Unknown status",
      parts?.stageLabel || job?.partsStage || "No active parts stage",
      job?.statusMeta?.categoryLabel || "Standard field workflow",
    ],
    checklist,
  };
}

function closeoutDraftKey(jobId) {
  return `fielddesk-closeout-draft-${jobId}`;
}

function readCloseoutDraft(jobId) {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(closeoutDraftKey(jobId));
    return raw ? { ...defaultCloseoutDraft(), ...JSON.parse(raw) } : null;
  } catch {
    return null;
  }
}

function persistCloseoutDraft(jobId, draft) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(closeoutDraftKey(jobId), JSON.stringify(draft));
}

function sanitizePhone(value) {
  return String(value || "").replace(/[^\d+]/g, "");
}

function describeStatusMeta(meta) {
  if (!meta || typeof meta !== "object") return "No structured job-state guidance loaded.";
  if (meta.isActiveParts) return "This job still has active parts work in flight.";
  if (meta.isQuoteNeeded) return "Office follow-up is needed before the next visit can be confirmed.";
  if (meta.isWaitingCustomer) return "Customer follow-up is the main blocker right now.";
  if (meta.isClosed) return "This SR is already in a closed state.";
  return meta.categoryLabel ? `${meta.categoryLabel} workflow is active.` : "Review the current SR state before updating the job.";
}
