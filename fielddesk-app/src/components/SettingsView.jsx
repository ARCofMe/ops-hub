export default function SettingsView({ config, onChange, onApply, onPing, pingState }) {
  return (
    <section className="panel stack-gap">
      <div className="section-head">
        <div>
          <p className="section-kicker">Client Settings</p>
          <h2>Wrapper-ready config</h2>
        </div>
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
      {pingState?.message && <p className={pingState.error ? "error-text" : "muted"}>{pingState.message}</p>}
    </section>
  );
}
