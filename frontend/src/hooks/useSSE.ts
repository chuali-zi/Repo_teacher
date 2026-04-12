import { useCallback, useRef } from 'react';

import type { CloseFn } from '../types/contracts';

export function useSSE() {
  const closeFnsRef = useRef<CloseFn[]>([]);

  const register = useCallback((closeFn: CloseFn) => {
    closeFnsRef.current.push(closeFn);
    return closeFn;
  }, []);

  const closeAll = useCallback(() => {
    closeFnsRef.current.forEach((closeFn) => closeFn());
    closeFnsRef.current = [];
  }, []);

  return { register, closeAll };
}

