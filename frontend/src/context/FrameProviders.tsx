// The frame-derived context stack, shared by the app shell (App.tsx) and the
// component-test helper (renderWithFrame) so tests render what production renders.
import type { ReactNode } from 'react';
import type { StateFrame } from '../types';
import { AgentsProvider } from './AgentsContext';
import { ConnectionProvider } from './ConnectionContext';
import { FrameMetaProvider } from './FrameMetaContext';
import { RationalesProvider } from './RationalesContext';
import { TelemetryProvider } from './TelemetryContext';

export function FrameProviders({
  frame,
  connected,
  reconnectFailed,
  children,
}: {
  frame: StateFrame;
  connected: boolean;
  reconnectFailed: boolean;
  children: ReactNode;
}) {
  return (
    <ConnectionProvider connected={connected} reconnectFailed={reconnectFailed} lastFrame={frame}>
      <FrameMetaProvider frame={frame}>
        <TelemetryProvider frame={frame}>
          <AgentsProvider frame={frame}>
            <RationalesProvider frame={frame}>{children}</RationalesProvider>
          </AgentsProvider>
        </TelemetryProvider>
      </FrameMetaProvider>
    </ConnectionProvider>
  );
}
