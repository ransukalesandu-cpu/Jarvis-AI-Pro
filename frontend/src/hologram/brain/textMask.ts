/** Rasterises a short text into a mask in the browser (bold, centred), for textPoints(). */
export function textMask(text: string, w = 512, h = 128): Uint8Array {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  const mask = new Uint8Array(w * h);
  if (!g) return mask;
  let size = h * 0.8;
  g.font = `800 ${size}px system-ui, sans-serif`;
  const fit = (w * 0.94) / Math.max(1, g.measureText(text).width);
  if (fit < 1) { size *= fit; g.font = `800 ${size}px system-ui, sans-serif`; }
  g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(text, w / 2, h / 2);
  const px = g.getImageData(0, 0, w, h).data;
  for (let i = 0; i < w * h; i++) mask[i] = px[i * 4 + 3];
  return mask;
}
