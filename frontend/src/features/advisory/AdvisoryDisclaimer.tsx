// Not-investment-advice banner for the advisory view. It is always shown and never dismissible.
import { ADVISORY_DISCLAIMER } from './disclaimer';

export function AdvisoryDisclaimer() {
  return (
    <div className="adv-disclaimer" role="note" aria-label="Disclaimer">
      {ADVISORY_DISCLAIMER}
    </div>
  );
}
