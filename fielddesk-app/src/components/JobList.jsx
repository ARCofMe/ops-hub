export default function JobList({
  jobs,
  selectedJobId,
  onSelectJob,
  title,
  subtitle,
  totalCount,
  filterText,
  filterScope,
  onFilterTextChange,
  onFilterScopeChange,
}) {
  return (
    <section className="panel stack-gap">
      <div className="section-head">
        <div>
          <p className="section-kicker">{subtitle}</p>
          <h2>{title}</h2>
        </div>
      </div>
      <div className="detail-grid compact-grid">
        <label className="field">
          <span>Find stop</span>
          <input value={filterText || ""} onChange={(event) => onFilterTextChange?.(event.target.value)} placeholder="Customer, SR, address" />
        </label>
        <label className="field">
          <span>Show</span>
          <select value={filterScope || "all"} onChange={(event) => onFilterScopeChange?.(event.target.value)}>
            <option value="all">All visible</option>
            <option value="open">Open only</option>
            <option value="parts">Parts blockers</option>
            <option value="done">Completed only</option>
          </select>
        </label>
      </div>
      <div className="chip-list">
        <span className="queue-chip">Visible: {jobs.length}</span>
        <span className="queue-chip">Total loaded: {totalCount ?? jobs.length}</span>
        <span className="queue-chip">Filter: {filterScope || "all"}</span>
      </div>
      <div className="list-stack">
        {jobs.map((job, index) => (
          <button
            key={job.id}
            type="button"
            className={String(selectedJobId) === String(job.id) ? "job-card selected" : "job-card"}
            onClick={() => onSelectJob(job)}
          >
            <div className="job-card-top">
              <strong>{job.customerName || `SR-${job.id}`}</strong>
              <span>{job.appointmentWindow || "Unscheduled"}</span>
            </div>
            <p>{job.address || "Address unavailable"}</p>
            <div className="job-card-meta">
              <span>Stop {index + 1}</span>
              <span>Status: {job.status || "unknown"}</span>
              <span>{job.partsStage || "No active parts stage"}</span>
            </div>
          </button>
        ))}
        {!jobs.length && <p className="muted">No jobs match the current queue filter.</p>}
      </div>
    </section>
  );
}
