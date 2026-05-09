// Inline icons — small, stroke-based, dir-agnostic (currentColor)
export const Icon = ({ name, size = 14 }) => {
  const s = size;
  const stroke = { stroke: 'currentColor', strokeWidth: 1.5, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' };
  switch (name) {
    case 'play':    return <svg width={s} height={s} viewBox="0 0 16 16"><path d="M4 3.5 L13 8 L4 12.5 Z" fill="currentColor" /></svg>;
    case 'pause':   return <svg width={s} height={s} viewBox="0 0 16 16"><rect x="4" y="3" width="3" height="10" fill="currentColor"/><rect x="9" y="3" width="3" height="10" fill="currentColor"/></svg>;
    case 'stop':    return <svg width={s} height={s} viewBox="0 0 16 16"><rect x="3" y="3" width="10" height="10" fill="currentColor"/></svg>;
    case 'bolt':    return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M9 1 L3 9 H8 L7 15 L13 7 H8 Z"/></svg>;
    case 'close':   return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M3 3 L13 13 M13 3 L3 13"/></svg>;
    case 'rewind':  return <svg width={s} height={s} viewBox="0 0 16 16"><path d="M13 3 L7 8 L13 13 Z M7 3 L3 8 L7 13 Z" fill="currentColor"/></svg>;
    case 'forward': return <svg width={s} height={s} viewBox="0 0 16 16"><path d="M3 3 L9 8 L3 13 Z M9 3 L13 8 L9 13 Z" fill="currentColor"/></svg>;
    case 'graph':   return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><circle cx="4" cy="4" r="2"/><circle cx="12" cy="4" r="2"/><circle cx="8" cy="12" r="2"/><path d="M5 5 L7 11 M11 5 L9 11 M6 4 L10 4"/></svg>;
    case 'grid':    return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><rect x="2" y="2" width="4" height="4"/><rect x="10" y="2" width="4" height="4"/><rect x="2" y="10" width="4" height="4"/><rect x="10" y="10" width="4" height="4"/></svg>;
    case 'radial':  return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="3"/><circle cx="8" cy="8" r="1" fill="currentColor"/></svg>;
    case 'chat':    return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M2 3 H14 V11 H8 L4 14 V11 H2 Z"/></svg>;
    case 'doc':     return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M4 2 H10 L13 5 V14 H4 Z M10 2 V5 H13 M6 8 H11 M6 11 H11"/></svg>;
    case 'replay':  return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M8 3 A5 5 0 1 0 13 8 M8 3 H11 M8 3 V6"/></svg>;
    case 'brief':   return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><rect x="2" y="5" width="12" height="9"/><path d="M6 5 V3 H10 V5"/></svg>;
    case 'search':  return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 L14 14"/></svg>;
    case 'lock':    return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><rect x="3" y="7" width="10" height="7"/><path d="M5 7 V5 A3 3 0 0 1 11 5 V7"/></svg>;
    case 'x':       return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><path d="M3 3 L13 13 M13 3 L3 13"/></svg>;
    case 'settings':return <svg width={s} height={s} viewBox="0 0 16 16" {...stroke}><circle cx="8" cy="8" r="2.2"/><path d="M8 1 V3 M8 13 V15 M1 8 H3 M13 8 H15 M3 3 L4.5 4.5 M11.5 11.5 L13 13 M3 13 L4.5 11.5 M11.5 4.5 L13 3"/></svg>;
    default: return null;
  }
};
