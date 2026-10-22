// Inference privacy facts for the copy in Settings, Data Sources and the Advisory
// isolation tab. Fetched once per mount; null while loading or when the settings
// endpoint fails, and the copy then says it is still checking instead of claiming
// "local" (docs/DECISIONS.md#adr-local-first-inference).
import { useEffect, useState } from 'react';
import { getSettings } from '../api/settings';
import { privacyFactsFromSettings, type PrivacyFacts } from '../lib/privacyCopy';

export function usePrivacyFacts(): PrivacyFacts | null {
  const [facts, setFacts] = useState<PrivacyFacts | null>(null);
  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((view) => {
        if (!cancelled) setFacts(privacyFactsFromSettings(view));
      })
      .catch(() => {
        if (!cancelled) setFacts(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return facts;
}
