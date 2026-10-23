// @vitest-environment happy-dom
import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { Icon, type IconName } from '../../components/icons';

afterEach(cleanup);

describe('Icon', () => {
  it('renders a sized stroke icon for a known name', () => {
    const { container } = render(<Icon name="bolt" size={20} />);
    const svg = container.querySelector('svg');
    expect(svg?.getAttribute('width')).toBe('20');
    expect(svg?.getAttribute('stroke')).toBe('currentColor');
  });

  it('defaults to 14px', () => {
    const { container } = render(<Icon name="play" />);
    expect(container.querySelector('svg')?.getAttribute('height')).toBe('14');
  });

  it('renders nothing for a name outside the union', () => {
    const { container } = render(<Icon name={'unknown' as IconName} />);
    expect(container.innerHTML).toBe('');
  });
});
