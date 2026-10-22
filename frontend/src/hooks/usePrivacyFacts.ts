// Inference privacy facts for the copy in Settings, Data Sources and the Advisory
// isolation tab. Fetched once per mount; null while loading or when the settings
// endpoint fails, and the copy then says it is still checking instead of claiming
// "local" (docs/DECISIONS.md#adr-local-first-inference). The second element
// rebuilds the facts from settings the caller already holds, such as the config a
// Settings save returned, so the copy never describes the config from before it.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getSettings, type SettingsView } from '../api/settings';
import { privacyFactsFromSettings, type PrivacyFacts } from '../lib/privacyCopy';

export function usePrivacyFacts(): [PrivacyFacts | null, (view: SettingsView) => void] {
  const [facts, setFacts] = useState<PrivacyFacts | null>(null);
  // Settings set by the caller are newer than a first fetch still in flight.
  const setByCaller = useRef(false);
  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((view) => {
        if (!cancelled && !setByCaller.current) setFacts(privacyFactsFromSettings(view));
      })
      .catch(() => {
        if (!cancelled && !setByCaller.current) setFacts(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const setFromSettings = useCallback((view: SettingsView) => {
    setByCaller.current = true;
    setFacts(privacyFactsFromSettings(view));
  }, []);
  return [facts, setFromSettings];
}
