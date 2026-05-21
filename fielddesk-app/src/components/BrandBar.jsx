export default function BrandBar({ activeJob, counts, onRefresh, refreshDisabled }) {
  return (
    <header className="brand-bar">
      <div className="brand-row">
        <div>
          <p className="section-kicker">Ops Hub Field Surface</p>
          <h1>FieldDesk</h1>
          <p className="muted">
            Mobile-first technician workflow over the Ops Hub technician API. This is the frontend that an Android wrapper should host.
          </p>
        </div>
        <button type="button" onClick={onRefresh} disabled={refreshDisabled}>
          Refresh
        </button>
      </div>
      <div className="chip-list">
        <span className="queue-chip">Queue: {counts.queue}</span>
        <span className="queue-chip">Visible: {counts.visible}</span>
        <span className="queue-chip">Next: {counts.next}</span>
        <span className="queue-chip">Done: {counts.done}</span>
        <span className="queue-chip">Pending: {counts.pending}</span>
        <span className="queue-chip">Parts: {counts.parts}</span>
        <span className="queue-chip">Unscheduled: {counts.unscheduled}</span>
        <span className="queue-chip">Active: {activeJob?.customerName || "none"}</span>
      </div>
    </header>
  );
}
