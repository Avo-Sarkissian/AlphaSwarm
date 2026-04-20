// Modals: Interview, Report, Shock, Replay, Advisory, CyclePicker.
// Plan 04 wiring: every modal now reads from the live backend via the REST
// wrappers in ../api/* (created by Task 1) and the shared Plan 02 infra
// (apiFetch/apiPost/ApiError, simShock, usePolling, useCurrentCycle).
import { useEffect, useMemo, useState } from 'react';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { Icon } from './icons';

import { askAgent } from '../api/interview';
import { reportGenerate, reportFetch } from '../api/report';
import { advisoryGenerate, advisoryFetch } from '../api/advisory';
import { listCycles, replayAdvance, replayStop } from '../api/replay';
import { fetchHoldings } from '../api/holdings';
import { simShock } from '../api/simulation';
import { ApiError } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { useCurrentCycle } from '../hooks/useCurrentCycle';
import { useTelemetry } from '../context/TelemetryContext';

// ─── Helpers ─────────────────────────────────────────────────────────────

function formatApiError(e) {
  if (e instanceof ApiError) {
    const detail =
      e.body && typeof e.body === 'object' && 'detail' in e.body
        ? e.body.detail
        : null;
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail
        ? detail.message
        : null;
    return message ? `HTTP ${e.status} — ${message}` : `HTTP ${e.status}`;
  }
  return String((e && e.message) || e || 'unknown error');
}

function renderMarkdown(source) {
  if (!source) return '';
  const rawHtml = marked.parse(source, { async: false });
  return DOMPurify.sanitize(typeof rawHtml === 'string' ? rawHtml : '');
}

// ─── InterviewModal ──────────────────────────────────────────────────────
// KR-41.1-11: backend returns a single JSON {response} — not SSE. This modal
// renders the full response as ONE block (no progressive token streaming).

export function InterviewModal({ agent, onClose }) {
  const signal = agent.signal ?? 'parse_error';
  const confidence = typeof agent.confidence === 'number' ? agent.confidence : 0;
  const [messages, setMessages] = useState(() => [
    {
      role: 'agent',
      text: `I'm ${agent.id}, bracket ${agent.bracketDisplay ?? agent.bracket ?? ''}. Final signal ${signal.toUpperCase()} at ${(confidence * 100).toFixed(0)}% confidence. Ask me to unpack any round, peer influence, or risk weighting.`,
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  async function send() {
    const userMsg = input.trim();
    if (!userMsg || loading) return;
    setMessages((m) => [...m, { role: 'user', text: userMsg }]);
    setInput('');
    setLoading(true);
    try {
      // KR-41.1-11: single POST → full response rendered as one block.
      const { response } = await askAgent(agent.id, userMsg);
      setMessages((m) => [...m, { role: 'agent', text: response }]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: 'agent', text: `[interview unavailable: ${formatApiError(e)}]` },
      ]);
    } finally {
      setLoading(false);
    }
  }

  const sigClass =
    signal === 'buy' ? 'sig-buy' : signal === 'sell' ? 'sig-sell' : 'sig-hold';

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="chat-avatar" style={{ width: 36, height: 36, fontSize: 12 }}>
              {agent.id}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {agent.id} ·{' '}
                <span style={{ color: 'var(--text-3)' }}>
                  {agent.bracketDisplay ?? agent.bracket ?? ''}
                </span>
              </div>
              <div className="label" style={{ marginTop: 2 }}>
                <span className={`rationale-signal ${sigClass}`}>
                  {signal.toUpperCase()}
                </span>
                <span style={{ marginLeft: 8 }}>
                  Conf {(confidence * 100).toFixed(0)}% · 3 rounds
                </span>
              </div>
            </div>
          </div>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" /> Close
          </button>
        </div>
        <div className="modal-body">
          <div className="chat-log">
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                <div className="chat-avatar">{m.role === 'user' ? 'YOU' : agent.id}</div>
                <div className="chat-bubble">{m.text}</div>
              </div>
            ))}
            {loading && (
              <div className="chat-msg agent">
                <div className="chat-avatar">{agent.id}</div>
                <div className="chat-bubble" style={{ color: 'var(--text-3)' }}>
                  thinking…
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="modal-foot" style={{ gap: 8 }}>
          <div className="seed-input" style={{ flex: 1 }}>
            <span className="prefix">›</span>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && send()}
              disabled={loading}
              placeholder={`Ask ${agent.id} about rationale, peer influence, risk weighting…`}
            />
          </div>
          <button
            className="btn primary"
            onClick={send}
            disabled={loading || !input.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── ReportModal ─────────────────────────────────────────────────────────

export function ReportModal({ cycleId: cycleIdProp, onClose }) {
  const fallback = useCurrentCycle();
  const cycleId = cycleIdProp ?? fallback.cycleId ?? null;

  const [kicked, setKicked] = useState(false);
  const [kickError, setKickError] = useState(null);

  // Kick off generation once per cycleId. 409 (another gen in flight) is not
  // an error — poll anyway. Non-409 errors surface in the UI.
  useEffect(() => {
    if (!cycleId || kicked) return;
    setKicked(true);
    reportGenerate(cycleId).catch((e) => {
      if (e instanceof ApiError && e.status === 409) return;
      setKickError(e);
    });
  }, [cycleId, kicked]);

  // Key-based polling — stable key ties the loop to cycleId.
  const { data, error } = usePolling({
    key: `report:${cycleId ?? 'none'}`,
    fetchFn: () =>
      cycleId ? reportFetch(cycleId) : Promise.resolve(null),
    intervalMs: 3000,
    maxAttempts: 200, // ~10 minutes at 3s
  });

  const html = useMemo(
    () => renderMarkdown(data?.content ?? ''),
    [data?.content],
  );

  const hadError = kickError || error;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-big" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <Icon name="doc" size={16} />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            REPORT · {cycleId ?? 'no cycle'}
          </span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" /> Close
          </button>
        </div>
        <div className="modal-body no-pad report">
          {!cycleId && (
            <div className="report-hero" style={{ padding: 24 }}>
              <div className="label">No completed cycle to report on.</div>
            </div>
          )}
          {cycleId && !data && !hadError && (
            <div className="report-hero" style={{ padding: 24 }}>
              <div className="label">Generating report…</div>
            </div>
          )}
          {hadError && !data && (
            <div
              className="report-hero"
              style={{ padding: 24, color: 'var(--sell)' }}
            >
              Report failed: {formatApiError(hadError)}
            </div>
          )}
          {data?.content && (
            <div
              className="report-markdown"
              style={{ padding: 24 }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ─── ShockDrawer ─────────────────────────────────────────────────────────
// Plan 02's simShock is the canonical source (reviewer item 17).
// Backend body: { shock_text: string }. The drawer builds the string from
// the selected preset / free-text input.

export function ShockDrawer({ onClose }) {
  const [text, setText] = useState(
    'DOJ files formal antitrust complaint against Apple–Anthropic deal',
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const presets = [
    'DOJ files formal antitrust complaint against Apple–Anthropic deal',
    'Fed cuts 50bp at emergency session',
    'Anthropic CEO denies acquisition talks publicly',
    'Treasury yields spike 40bp on inflation print',
  ];

  async function onInject() {
    const shockText = text.trim();
    if (!shockText || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await simShock(shockText);
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
      return; // don't close on error — user can retry
    }
    setBusy(false);
    onClose();
  }

  return (
    <div className="shock-drawer">
      <div className="hflex" style={{ marginBottom: 10 }}>
        <Icon name="bolt" size={14} />
        <span className="label" style={{ color: 'var(--sell)' }}>
          Shock Injection · between rounds 2 &amp; 3
        </span>
        <div className="sp" />
        <button className="btn ghost" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <div className="seed-input" style={{ marginBottom: 10 }}>
        <span className="prefix">⚡</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Disruptive event text…"
          disabled={busy}
        />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
        {presets.map((p) => (
          <button
            key={p}
            className="btn ghost"
            style={{ fontSize: 10, height: 26 }}
            onClick={() => setText(p)}
            disabled={busy}
          >
            {p.length > 40 ? p.slice(0, 40) + '…' : p}
          </button>
        ))}
      </div>
      {err && (
        <div
          className="shock-error"
          style={{
            color: 'var(--sell)',
            fontSize: 11,
            marginBottom: 8,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          {err}
        </div>
      )}
      <div className="hflex">
        <span className="label">
          Impact preview · ~{Math.floor(20 + text.length * 0.7)} agents re-evaluate
        </span>
        <div className="sp" />
        <button className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn primary" onClick={onInject} disabled={busy || !text.trim()}>
          <Icon name="bolt" /> {busy ? 'Injecting…' : 'Inject'}
        </button>
      </div>
    </div>
  );
}

// ─── AdvisoryModal ───────────────────────────────────────────────────────

export function AdvisoryModal({ cycleId: cycleIdProp, onClose }) {
  const fallback = useCurrentCycle();
  const cycleId = cycleIdProp ?? fallback.cycleId ?? null;

  const [kicked, setKicked] = useState(false);
  const [kickError, setKickError] = useState(null);
  const [holdings, setHoldings] = useState([]);

  useEffect(() => {
    if (!cycleId || kicked) return;
    setKicked(true);
    advisoryGenerate(cycleId).catch((e) => {
      // 409 = either report or advisory already in flight — poll anyway.
      if (e instanceof ApiError && e.status === 409) return;
      setKickError(e);
    });
  }, [cycleId, kicked]);

  useEffect(() => {
    let cancelled = false;
    fetchHoldings()
      .then((snap) => {
        if (!cancelled) setHoldings(snap.holdings ?? []);
      })
      .catch(() => {
        if (!cancelled) setHoldings([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { data, error } = usePolling({
    key: `advisory:${cycleId ?? 'none'}`,
    fetchFn: () =>
      cycleId ? advisoryFetch(cycleId) : Promise.resolve(null),
    intervalMs: 3000,
    maxAttempts: 200,
  });

  const html = useMemo(() => {
    const content =
      (data &&
        (typeof data.content === 'string'
          ? data.content
          : typeof data.narrative === 'string'
          ? data.narrative
          : '')) || '';
    return renderMarkdown(content);
  }, [data]);

  const hadError = kickError || error;

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-big" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <Icon name="brief" size={16} />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            PERSONALIZED ADVISORY · {cycleId ?? 'no cycle'}
          </span>
          <span
            style={{
              marginLeft: 8,
              padding: '2px 6px',
              border: '1px solid var(--border)',
              borderRadius: 3,
              fontSize: 10,
              fontFamily: 'JetBrains Mono',
              color: 'var(--accent)',
            }}
          >
            ORCHESTRATOR-ONLY
          </span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" /> Close
          </button>
        </div>
        <div className="modal-body">
          {!cycleId && (
            <div className="advisory-card">
              <div className="label">No completed cycle to advise on.</div>
            </div>
          )}
          {cycleId && !data && !hadError && (
            <div className="advisory-card">
              <div className="label">Synthesizing advisory…</div>
            </div>
          )}
          {hadError && !data && (
            <div className="advisory-card" style={{ color: 'var(--sell)' }}>
              Advisory failed: {formatApiError(hadError)}
            </div>
          )}
          {data && html && (
            <div
              className="advisory-markdown"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          )}
          {holdings.length > 0 && (
            <aside
              className="advisory-holdings"
              style={{
                marginTop: 14,
                padding: 14,
                border: '1px solid var(--border)',
                borderRadius: 6,
              }}
            >
              <div className="label" style={{ marginBottom: 8 }}>
                Portfolio context
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
                {holdings.map((h) => (
                  <li
                    key={h.ticker}
                    style={{
                      fontSize: 12,
                      color: 'var(--text-2)',
                      marginBottom: 4,
                      fontFamily: 'JetBrains Mono, monospace',
                    }}
                  >
                    {h.ticker} — {h.qty}
                    {h.cost_basis ? ` @ $${h.cost_basis}` : ''}
                  </li>
                ))}
              </ul>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── ReplayBar ───────────────────────────────────────────────────────────
// Rewind is deliberately disabled — backend exposes advance/stop only.
// KR-41.1-06: Rewind button disabled pending a backend rewind endpoint.

export function ReplayBar({ cycle, onExit }) {
  const { roundNum } = useTelemetry();
  const round = roundNum ?? 1;
  const [busy, setBusy] = useState(false);

  async function onForward() {
    if (busy) return;
    setBusy(true);
    try {
      await replayAdvance();
    } catch (e) {
      // best-effort — log, do not block UI
      // KR-41.1-08: errors console.logged; structured error stream deferred.
      console.error('replay advance failed', e);
    } finally {
      setBusy(false);
    }
  }

  async function onExitReplay() {
    if (busy) return;
    setBusy(true);
    try {
      await replayStop();
    } catch (e) {
      console.error('replay stop failed', e);
    } finally {
      setBusy(false);
    }
    if (onExit) onExit();
  }

  return (
    <div className="replay-bar">
      <div className="label" style={{ color: 'var(--accent)' }}>
        <Icon name="replay" size={11} /> REPLAY · {cycle?.cycle_id ?? cycle?.id ?? ''}
      </div>
      {/* KR-41.1-06: Rewind disabled — no backend endpoint yet. */}
      <button
        className="btn ghost"
        disabled
        title="Rewind not supported (KR-41.1-06)"
      >
        <Icon name="rewind" />
      </button>
      <div className="replay-track">
        <div className="replay-fill" style={{ width: `${(round / 3) * 100}%` }} />
        <div className="replay-ticks">
          {['SEED', 'R1', 'R2', 'R3'].map((t, i) => (
            <span
              key={t}
              style={{ color: i <= round ? 'var(--accent)' : 'var(--text-3)' }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>
      <button
        className="btn ghost"
        onClick={onForward}
        disabled={busy || round >= 3}
      >
        <Icon name="forward" />
      </button>
      <button className="btn" onClick={onExitReplay} disabled={busy}>
        Exit replay
      </button>
    </div>
  );
}

// ─── CyclePickerModal ────────────────────────────────────────────────────

export function CyclePickerModal({ onPick, onClose }) {
  const [cycles, setCycles] = useState(null); // null = loading
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listCycles()
      .then((cs) => {
        if (!cancelled) setCycles(cs);
      })
      .catch((e) => {
        if (cancelled) return;
        // KR-41.1-08: errors console.logged + surfaced to UI label.
        console.error('listCycles failed', e);
        setErr(e);
        setCycles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(720px, 94%)' }}
      >
        <div className="modal-head">
          <Icon name="replay" />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            SELECT CYCLE TO REPLAY
          </span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="modal-body no-pad">
          {cycles === null && (
            <div style={{ padding: '30px 20px' }} className="label">
              Loading cycles…
            </div>
          )}
          {err && (
            <div
              style={{ padding: '30px 20px', color: 'var(--sell)' }}
              className="label"
            >
              {formatApiError(err)}
            </div>
          )}
          {cycles && cycles.length === 0 && !err && (
            <div style={{ padding: '30px 20px' }} className="label">
              No completed cycles yet.
            </div>
          )}
          {cycles &&
            cycles.map((c) => (
              <div
                key={c.cycle_id}
                style={{
                  padding: '14px 20px',
                  borderBottom: '1px solid var(--border)',
                  cursor: 'pointer',
                  display: 'grid',
                  gridTemplateColumns: '1fr auto auto',
                  gap: 18,
                  alignItems: 'center',
                }}
                onClick={() => onPick(c)}
                onMouseOver={(e) => (e.currentTarget.style.background = 'var(--bg-3)')}
                onMouseOut={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <div>
                  <div style={{ fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
                    "{c.seed_rumor}"
                  </div>
                  <div className="label">{c.cycle_id}</div>
                </div>
                <div className="label">{c.created_at}</div>
                <div className="label">{c.round_count}R</div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
