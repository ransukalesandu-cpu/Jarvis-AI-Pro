import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Spark } from './Spark';

describe('Spark', () => {
  it('draws no line and says so without data', () => {
    const h = renderToStaticMarkup(<Spark label="CPU" data={[]} unit="%" max={100} />);
    expect(h).not.toContain('<polyline');
    expect(h).toContain('no samples yet');
  });
  it('draws a line and a numeric text equivalent with data', () => {
    const h = renderToStaticMarkup(<Spark label="CPU" data={[10, 50, 30]} unit="%" max={100} />);
    expect(h).toContain('<polyline');
    expect(h).toContain('now 30%, min 10, max 50');
  });
});
