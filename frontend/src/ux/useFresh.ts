import { useEffect, useState } from 'react';

/** A status note that clears itself: returns `value` for `ms` after it last changed, then null.
 *  `key` changes on every new result so the same reason twice still shows again. */
export function useFresh<T>(value: T | null, key: unknown, ms = 5000): T | null {
  const [shown, setShown] = useState<T | null>(value);
  useEffect(() => {
    setShown(value);
    if (value === null) return;
    const id = setTimeout(() => setShown(null), ms);
    return () => clearTimeout(id);
  }, [value, key, ms]);
  return shown;
}
