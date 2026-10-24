// @vitest-environment happy-dom
// Every inference-settings field is labelled, and the two role forms on one
// page never share an id.
import type { ComponentProps } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RoleForm } from '../../features/settings/RoleForm';

type Props = ComponentProps<typeof RoleForm>;

const props: Props = {
  roleLabel: 'Worker',
  roleKey: 'worker',
  form: { provider: 'openai_compatible', model: 'zzzt-model', base_url: 'http://127.0.0.1:9', api_key: '' },
  originalView: {
    provider: 'openai_compatible',
    model: 'zzzt-model',
    base_url: 'http://127.0.0.1:9',
    api_key: { set: false, last4: null },
  },
  availableLocalModels: [],
  knownApiModels: [],
  presets: [{ label: 'Example preset', provider: 'openai_compatible', base_url: 'http://127.0.0.1:9', models: ['zzzt-model'] }],
  onChange: vi.fn(),
  onReplace: vi.fn(),
};

afterEach(cleanup);

describe('RoleForm labels', () => {
  it('labels every field', () => {
    render(<RoleForm {...props} />);
    for (const name of ['Preset', 'Provider', 'Model', 'Base URL', 'API key']) {
      expect(screen.getByLabelText(name)).toBeTruthy();
    }
  });

  it('keeps ids unique when both roles render', () => {
    render(
      <>
        <RoleForm {...props} />
        <RoleForm {...props} roleLabel="Orchestrator" roleKey="orchestrator" />
      </>,
    );
    const ids = screen.getAllByLabelText('Model').map((el) => el.id);
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
  });
});
