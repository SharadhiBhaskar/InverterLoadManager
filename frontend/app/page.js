"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function errorText(data) {
  if (!data) {
    return "The request failed.";
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg).join(" ");
  }
  return "The request failed.";
}

function noticeTone(text) {
  if (!text) {
    return "ok";
  }
  if (text.includes("Nothing was changed") || text.includes("failed") || text.includes("Cannot reach")) {
    return "bad";
  }
  if (text.includes("shed")) {
    return "warn";
  }
  return "ok";
}

export default function Home() {
  const [status, setStatus] = useState(null);
  const [notice, setNotice] = useState("");
  const [offline, setOffline] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [form, setForm] = useState({ name: "", wattage: "", priority: "" });

  const refresh = useCallback(async () => {
    try {
      const response = await fetch(`${API}/status`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error("status");
      }
      setStatus(await response.json());
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function send(url, options) {
    const response = await fetch(url, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      setNotice(errorText(data));
      await refresh();
      return false;
    }
    if (data && data.message) {
      setNotice(data.message);
    }
    await refresh();
    return true;
  }

  async function setPower(appliance, direction) {
    setBusyId(appliance.id);
    try {
      await send(`${API}/appliances/${appliance.id}/${direction}`, { method: "POST" });
    } finally {
      setBusyId(null);
    }
  }

  async function remove(appliance) {
    if (!window.confirm(`Delete ${appliance.name}?`)) {
      return;
    }
    setBusyId(appliance.id);
    try {
      await send(`${API}/appliances/${appliance.id}`, { method: "DELETE" });
    } finally {
      setBusyId(null);
    }
  }

  async function register(event) {
    event.preventDefault();
    setBusyId("form");
    try {
      const saved = await send(`${API}/appliances`, {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          wattage: Number(form.wattage),
          priority: Number(form.priority),
        }),
      });
      if (saved) {
        setForm({ name: "", wattage: "", priority: "" });
      }
    } finally {
      setBusyId(null);
    }
  }

  const capacity = status?.capacity_watts ?? 800;
  const load = status?.load_watts ?? 0;
  const remaining = status?.remaining_watts ?? capacity;
  const usedPercent = Math.min(100, Math.round((load / capacity) * 100));

  return (
    <main className="app">
      <header className="header">
        <div>
          <h1>Inverter Load Manager</h1>
          <p>Priority 1 stays on first. The limit is {capacity}W.</p>
        </div>
        <button className="refresh" type="button" onClick={refresh}>
          Refresh
        </button>
      </header>

      <section className="capacity">
        <div className="capacity-top">
          <strong>{load}W used</strong>
          <span>{remaining}W free</span>
        </div>
        <div
          className="bar"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={capacity}
          aria-valuenow={load}
          aria-label="Watts in use"
        >
          <div className={load >= capacity ? "bar-used full" : "bar-used"} style={{ width: `${usedPercent}%` }} />
        </div>
      </section>

      {offline ? (
        <p className="notice bad">Cannot reach the API at {API}. Start the backend, then press Refresh.</p>
      ) : null}
      {notice ? <p className={`notice ${noticeTone(notice)}`}>{notice}</p> : null}

      <section className="panel">
        <h2>Add an appliance</h2>
        <form className="form" onSubmit={register}>
          <label>
            Name
            <input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </label>
          <label>
            Watts
            <input
              type="number"
              min="1"
              value={form.wattage}
              onChange={(event) => setForm({ ...form, wattage: event.target.value })}
              required
            />
          </label>
          <label>
            Priority
            <input
              type="number"
              min="1"
              value={form.priority}
              onChange={(event) => setForm({ ...form, priority: event.target.value })}
              required
            />
          </label>
          <button className="primary" type="submit" disabled={busyId === "form"}>
            Register
          </button>
        </form>
        <p className="hint">1 is the most important. A bigger number matters less.</p>
      </section>

      <section className="list">
        {status && status.appliances.length === 0 ? <p className="empty">No appliances yet.</p> : null}
        {status?.appliances.map((appliance) => (
          <article className={`appliance ${appliance.state}`} key={appliance.id}>
            <div>
              <div className="title-row">
                <h3 className="name">{appliance.name}</h3>
                <span className={`state ${appliance.state}`}>{appliance.state}</span>
              </div>
              <p className="meta">
                {appliance.wattage}W
                <span className="dot">·</span>
                Priority {appliance.priority}
                {appliance.priority === 1 ? " · most important" : ""}
              </p>
              {appliance.state === "shed" ? (
                <p className="waiting">Paused by the inverter. Waiting to come back.</p>
              ) : null}
            </div>
            <div className="controls">
              <div className="switch" role="group" aria-label={`${appliance.name} power`}>
                <button
                  type="button"
                  className={appliance.state === "running" ? "selected on" : ""}
                  disabled={busyId === appliance.id}
                  onClick={() => setPower(appliance, "on")}
                >
                  On
                </button>
                <button
                  type="button"
                  className={appliance.state === "off" ? "selected off" : ""}
                  disabled={busyId === appliance.id}
                  onClick={() => setPower(appliance, "off")}
                >
                  Off
                </button>
              </div>
              <button className="delete" type="button" onClick={() => remove(appliance)}>
                Delete
              </button>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
