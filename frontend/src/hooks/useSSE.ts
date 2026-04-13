import { useCallback, useRef } from 'react';

import type { CloseFn } from '../types/contracts';

export function useSSE() {
  const closeFnsRef = useRef(new Map<string, CloseFn>());

  const register = useCallback((key: string, closeFn: CloseFn) => {
    closeFnsRef.current.get(key)?.();
    closeFnsRef.current.set(key, closeFn);
    return closeFn;
  }, []);

  const close = useCallback((key: string) => {
    closeFnsRef.current.get(key)?.();
    closeFnsRef.current.delete(key);
  }, []);

  const closeAll = useCallback(() => {
    closeFnsRef.current.forEach((closeFn) => closeFn());
    closeFnsRef.current.clear();
  }, []);

  return { register, close, closeAll };
}
