// Tweaks panel — host-integrated
import { Icon } from './icons';

export function TweaksPanel({ state, setState, onClose }) {
  const { layout, density, phase, sigMix } = state;
  const setMix = (key, val) => {
    const v = Math.max(0, Math.min(100, Number(val) || 0));
    setState(s => ({ ...s, sigMix: { ...s.sigMix, [key]: v/100 } }));
  };
  return (
    <div className="tweaks-panel">
      <div className="tweaks-head">
        <div className="hflex"><Icon name="settings" /> <span style={{fontFamily:'JetBrains Mono', fontSize:11, letterSpacing:'0.12em', textTransform:'uppercase'}}>Tweaks</span></div>
        <button className="btn ghost" style={{height:24, padding:'0 6px'}} onClick={onClose}><Icon name="close" /></button>
      </div>
      <div className="tweaks-body">
        <div className="tweak-group">
          <span className="tweak-label">Layout</span>
          <div className="seg">
            {[
              { k: 'force', label: 'Force' },
              { k: 'radial', label: 'Radial' },
              { k: 'grid', label: 'Grid' },
            ].map(l => (
              <button key={l.k} data-active={layout === l.k} onClick={() => setState(s => ({...s, layout: l.k}))}>{l.label}</button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Density</span>
          <div className="seg">
            <button data-active={density==='compact'} onClick={() => setState(s=>({...s, density:'compact'}))}>Compact</button>
            <button data-active={density==='comfortable'} onClick={() => setState(s=>({...s, density:'comfortable'}))}>Comfortable</button>
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Phase</span>
          <div className="seg">
            {['1','2','3','done'].map(p => (
              <button key={p} data-active={String(phase) === p} onClick={() => setState(s => ({...s, phase: p === 'done' ? 'done' : Number(p)}))}>
                {p === 'done' ? 'Final' : `R${p}`}
              </button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Demo state</span>
          <div className="seg seg-wrap">
            {[
              { k: 'live',    label: 'Live' },
              { k: 'idle',    label: 'Idle' },
              { k: 'seeding', label: 'Seeding' },
              { k: 'mempause',label: 'Mem ceiling' },
              { k: 'error',   label: 'Error' },
            ].map(o => (
              <button key={o.k} data-active={(state.demoState || 'live') === o.k}
                onClick={() => setState(s => ({...s, demoState: o.k}))}>{o.label}</button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Signal distribution</span>
          <div className="sig-mix">
            <label><span className="buy">BUY %</span><input type="number" min="0" max="100" value={Math.round(sigMix.buy*100)} onChange={e=>setMix('buy', e.target.value)} /></label>
            <label><span className="sell">SELL %</span><input type="number" min="0" max="100" value={Math.round(sigMix.sell*100)} onChange={e=>setMix('sell', e.target.value)} /></label>
            <label><span className="hold">HOLD %</span><input type="number" min="0" max="100" value={Math.round(sigMix.hold*100)} onChange={e=>setMix('hold', e.target.value)} /></label>
          </div>
          <div style={{fontSize:10, color:'var(--text-3)', fontFamily:'JetBrains Mono', marginTop:4}}>Normalized automatically. Bracket biases applied on top.</div>
        </div>
      </div>
    </div>
  );
}
