// Inference privacy facts for the copy in Settings, Data Sources and the Advisory
// isolation tab. Fetched once per mount: null while loading, FACTS_UNAVAILABLE when
// the settings endpoint fails, and the copy then says it is still checking or that
// it cannot tell, instead of claiming "local"
// (docs/DECISIONS.md#adr-local-first-inference). The second element rebuilds the
// facts from settings the caller already holds, such as the config a Settings save
// returned, so the copy never describes the config from before it.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getSettings, type SettingsView } from '../api/settings';
import {
  FACTS_UNAVAILABLE,
  privacyFactsFromSettings,
  type PrivacyStatus,
} from '../lib/privacyCopy';

export function usePrivacyFacts(): [PrivacyStatus, (view: SettingsView) => void] {
  const [facts, setFacts] = useState<PrivacyStatus>(null);
  // Settings set by the caller are newer than a first fetch still in flight.
  const setByCaller = useRef(false);
  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((view) => {
        if (!cancelled && !setByCaller.current) setFacts(privacyFactsFromSettings(view));
      })
      .catch(() => {
        if (!cancelled && !setByCaller.current) setFacts(FACTS_UNAVAILABLE);
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
