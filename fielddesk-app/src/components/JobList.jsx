export default function JobList({
  jobs,
  groupedJobs,
  compact,
  selectedJobId,
  onSelectJob,
  title,
  subtitle,
  totalCount,
  filterText,
  filterScope,
  onFilterTextChange,
  onFilterScopeChange,
  onClearFilters,
}) {
  const hasFilters = Boolean((filterText || "").trim()) || (filterScope || "all") !== "all";
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
            <option value="next">Next stops</option>
            <option value="open">Open only</option>
            <option value="parts">Parts blockers</option>
            <option value="unscheduled">Unscheduled</option>
            <option value="done">Completed only</option>
          </select>
        </label>
      </div>
      <div className="chip-list">
        <span className="queue-chip">Visible: {jobs.length}</span>
        <span className="queue-chip">Total loaded: {totalCount ?? jobs.length}</span>
        <span className="queue-chip">Filter: {filterScope || "all"}</span>
        {hasFilters && (
          <button type="button" className="secondary-button compact-filter-button" onClick={onClearFilters}>
            Clear filters
          </button>
        )}
      </div>
      {Array.isArray(groupedJobs) && groupedJobs.length ? (
        <div className={compact ? "list-stack compact-list" : "list-stack"}>
          {groupedJobs.map((group) => (
            <section key={group.label} className="detail-block grouped-list">
              <div className="section-head compact">
                <strong>{group.label}</strong>
                <span className="muted">{group.items.length}</span>
              </div>
              <div className={compact ? "list-stack compact-list" : "list-stack"}>
                {group.items.map((job, index) => (
                  <JobCard key={job.id} job={job} index={index} compact={compact} selectedJobId={selectedJobId} onSelectJob={onSelectJob} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className={compact ? "list-stack compact-list" : "list-stack"}>
          {jobs.map((job, index) => (
            <JobCard key={job.id} job={job} index={index} compact={compact} selectedJobId={selectedJobId} onSelectJob={onSelectJob} />
          ))}
          {!jobs.length && <p className="muted">No jobs match the current queue filter.</p>}
        </div>
      )}
    </section>
  );
}

function JobCard({ job, index, compact, selectedJobId, onSelectJob }) {
  return (
    <button
      type="button"
      className={[String(selectedJobId) === String(job.id) ? "job-card selected" : "job-card", compact ? "compact-entry" : ""].filter(Boolean).join(" ")}
      onClick={() => onSelectJob(job)}
    >
      <div className="job-card-top">
        <strong>{job.customerName || `SR-${job.id}`}</strong>
        <span>{job.appointmentWindow || "Unscheduled"}</span>
      </div>
      {!compact && <p>{job.address || "Address unavailable"}</p>}
      <div className="job-card-meta">
        <span>Stop {index + 1}</span>
        <span>Status: {job.status || "unknown"}</span>
        <span>{job.partsStage || "No active parts stage"}</span>
        {job.rankLabel && <span>{job.rankLabel}</span>}
      </div>
    </button>
  );
}
