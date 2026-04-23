export default function JobList({ jobs, selectedJobId, onSelectJob, title, subtitle }) {
  return (
    <section className="panel stack-gap">
      <div className="section-head">
        <div>
          <p className="section-kicker">{subtitle}</p>
          <h2>{title}</h2>
        </div>
      </div>
      <div className="list-stack">
        {jobs.map((job, index) => (
          <button
            key={job.id}
            type="button"
            className={selectedJobId === job.id ? "job-card selected" : "job-card"}
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
        {!jobs.length && <p className="muted">No jobs are currently visible for this technician.</p>}
      </div>
    </section>
  );
}
