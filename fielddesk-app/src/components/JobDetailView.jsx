import { useMemo, useState } from "react";

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
}) {
  const [note, setNote] = useState("");
  const [partsNeed, setPartsNeed] = useState("");
  const [quoteNeed, setQuoteNeed] = useState("");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [photoLabel, setPhotoLabel] = useState("before");

  const sortedTimeline = useMemo(
    () => [...(timeline || [])].sort((left, right) => String(right.occurredAt || "").localeCompare(String(left.occurredAt || ""))),
    [timeline]
  );

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
      </div>

      <div className="detail-block">
        <strong>Customer and stop</strong>
        <p>{job.address || "Address unavailable"}</p>
        <p className="muted">{describeStatusMeta(job.statusMeta)}</p>
      </div>

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
        </div>
        <div className="chip-list">
          <span className="queue-chip">Found: {formatList(photos?.foundTags)}</span>
          <span className="queue-chip">Missing: {formatList(photos?.missingTags)}</span>
        </div>
      </div>

      {actionState?.message && <p className={actionState.error ? "error-text" : "muted"}>{actionState.message}</p>}

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

function describeStatusMeta(meta) {
  if (!meta || typeof meta !== "object") return "No structured job-state guidance loaded.";
  if (meta.isActiveParts) return "This job still has active parts work in flight.";
  if (meta.isQuoteNeeded) return "Office follow-up is needed before the next visit can be confirmed.";
  if (meta.isWaitingCustomer) return "Customer follow-up is the main blocker right now.";
  if (meta.isClosed) return "This SR is already in a closed state.";
  return meta.categoryLabel ? `${meta.categoryLabel} workflow is active.` : "Review the current SR state before updating the job.";
}
