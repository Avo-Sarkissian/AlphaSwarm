// @vitest-environment happy-dom
import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { IdleState } from '../../features/dashboard/StateOverlays';
import { HEALTH_ALIAS_MISSING } from '../fixtures/health';
import wsSnapshot from '../fixtures/ws_snapshot.json';
import { requestedUrls, stubFetch } from '../helpers/fetchStub';
import { renderWithFrame } from '../helpers/renderWithFrame';

afterEach(() => vi.unstubAllGlobals());

describe('IdleState', () => {
  it('renders backend components with their fix and no hard-coded rows or dead tips', async () => {
    const mock = stubFetch([{ path: '/api/health', body: HEALTH_ALIAS_MISSING }]);
    renderWithFrame(<IdleState seed="" numRounds={3} />, { raw: wsSnapshot });
    expect(await screen.findByText('missing: alphaswarm-worker')).toBeTruthy();
    expect(screen.getByText('ollama create alphaswarm-worker -f modelfiles/Modelfile.worker')).toBeTruthy();
    expect(requestedUrls(mock)).toContain('/api/health');
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/~\/\.alphaswarm|mocked · pending live wire|press R to run|qwen3\.6:35b-a3b-nvfp4 \(MLX\)/);
  });
});
