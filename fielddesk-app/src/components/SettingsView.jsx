export default function SettingsView({ config, onChange, onApply, onPing, pingState }) {
  const readiness = [
    ["API base", Boolean(config.apiBase)],
    ["Token", Boolean(config.apiToken)],
    ["Technician", Boolean(config.technicianSubject)],
    ["HTTP base", /^https?:\/\//i.test(config.apiBase || "")],
    ["Timeout", Number(config.timeoutMs) >= 5000 && Number(config.timeoutMs) <= 120000],
  ];
  const readyCount = readiness.filter(([, ready]) => ready).length;

  return (
    <section className="panel stack-gap">
      <div className="section-head">
        <div>
          <p className="section-kicker">Client Settings</p>
          <h2>Wrapper-ready config</h2>
        </div>
      </div>
      <div className="detail-grid">
        <div className="detail-value">
          <span>Device readiness</span>
          <strong>{readyCount} / {readiness.length}</strong>
        </div>
        {readiness.map(([label, ready]) => (
          <div key={label} className="detail-value">
            <span>{label}</span>
            <strong>{ready ? "Ready" : "Missing"}</strong>
          </div>
        ))}
      </div>
      <label className="field">
        <span>Ops Hub API base</span>
        <input value={config.apiBase} onChange={(event) => onChange("apiBase", event.target.value)} placeholder="http://127.0.0.1:8787" />
      </label>
      <label className="field">
        <span>Technician API token</span>
        <input value={config.apiToken} onChange={(event) => onChange("apiToken", event.target.value)} placeholder="ops-hub technician token" />
      </label>
      <label className="field">
        <span>Technician subject</span>
        <input value={config.technicianSubject} onChange={(event) => onChange("technicianSubject", event.target.value)} placeholder="bf:12345 or mapped subject" />
      </label>
      <label className="field">
        <span>Theme</span>
        <select value={config.themeMode} onChange={(event) => onChange("themeMode", event.target.value)}>
          <option value="dark">Dark</option>
          <option value="light">Light</option>
        </select>
      </label>
      <label className="field">
        <span>Request timeout</span>
        <input
          type="number"
          min="5"
          max="120"
          value={Math.round((Number(config.timeoutMs) || 30000) / 1000)}
          onChange={(event) => onChange("timeoutMs", Number(event.target.value) * 1000)}
        />
      </label>
      <label className="field">
        <span>Ops Hub workspace URL</span>
        <input value={config.opsHubUrl || ""} onChange={(event) => onChange("opsHubUrl", event.target.value)} placeholder="https://ops-hub.example" />
      </label>
      <label className="field">
        <span>RouteDesk URL</span>
        <input value={config.routeDeskUrl || ""} onChange={(event) => onChange("routeDeskUrl", event.target.value)} placeholder="https://route.example" />
      </label>
      <label className="field">
        <span>PartsDesk URL</span>
        <input value={config.partsDeskUrl || ""} onChange={(event) => onChange("partsDeskUrl", event.target.value)} placeholder="https://parts.example" />
      </label>
      <div className="action-row">
        <button type="button" onClick={onApply}>Apply settings</button>
        <button type="button" className="secondary-button" onClick={onPing}>Check connection</button>
      </div>
      <p className="muted">
        FieldDesk settings are local to this technician device. RouteDesk and PartsDesk URLs are optional handoff links,
        not a shared FieldDesk launcher.
      </p>
      {pingState?.message && <p className={pingState.error ? "error-text" : "muted"}>{pingState.message}</p>}
    </section>
  );
}
