float holoScanlines(float y, float time, float density, float speed) {
  return 0.5 + 0.5 * sin((y * density - time * speed) * 6.2831853);
}
