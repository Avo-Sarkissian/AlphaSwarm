// Plays a replay from Round 1 to the last round at a fixed pace. The frame is
// the clock: the next seek is scheduled only after the frame shows the round
// the previous seek asked for, so a slow backend never skips a round
// (docs/DECISIONS.md#adr-replaystore-separate).
import { useCallback, useEffect, useState } from 'react';
import { formatApiError } from '../lib/apiError';

export const CASCADE_STEP_MS = 2500;

export interface CascadePlayer {
  playing: boolean;
  error: string | null;
  play(): void;
  stop(): void;
  seek(round: number): void;
  dismissError(): void;
}

export function useCascadePlayer(opts: {
  roundNum: number | null;
  numRounds: number;
  seek: (round: number) => Promise<unknown>;
}): CascadePlayer {
  const { roundNum, numRounds, seek: seekRound } = opts;
  const [playing, setPlaying] = useState(false);
  const [requested, setRequested] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const go = useCallback(
    (round: number) => {
      setRequested(round);
      seekRound(round).catch((e: unknown) => {
        setPlaying(false);
        setRequested(null);
        setError(formatApiError(e));
      });
    },
    [seekRound],
  );

  const play = useCallback(() => {
    setError(null);
    setPlaying(true);
    if (roundNum === 1) setRequested(1);
    else go(1);
  }, [go, roundNum]);

  const stop = useCallback(() => {
    setPlaying(false);
    setRequested(null);
  }, []);

  const seek = useCallback(
    (round: number) => {
      setPlaying(false);
      setError(null);
      go(round);
    },
    [go],
  );

  const dismissError = useCallback(() => setError(null), []);

  useEffect(() => {
    if (!playing || roundNum === null) return;
    if (requested !== null && roundNum !== requested) return;
    const timer = setTimeout(() => {
      if (roundNum >= numRounds) {
        setPlaying(false);
        setRequested(null);
      } else {
        go(roundNum + 1);
      }
    }, CASCADE_STEP_MS);
    return () => clearTimeout(timer);
  }, [playing, roundNum, requested, numRounds, go]);

  return { playing, error, play, stop, seek, dismissError };
}
