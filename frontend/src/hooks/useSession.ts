import { useCallback, useEffect, useReducer, useState } from 'react';

import { chatApiClient, repoApiClient, streamClient } from '../api/client';
import {
  initialClientSessionStore,
  sessionReducer
} from '../store/sessionStore';
import type { ValidateRepoData } from '../types/contracts';
import { useSSE } from './useSSE';

export function useSession() {
  const [store, dispatch] = useReducer(sessionReducer, initialClientSessionStore);
  const [inputValue, setInputValue] = useState('');
  const [validation, setValidation] = useState<ValidateRepoData | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { register, closeAll } = useSSE();

  useEffect(() => {
    let cancelled = false;
    repoApiClient.getSession().then((response) => {
      if (!cancelled && response.ok) {
        dispatch({ type: 'snapshot', snapshot: response.data });
      }
    });
    return () => {
      cancelled = true;
      closeAll();
    };
  }, [closeAll]);

  const validate = useCallback(async (value: string) => {
    const response = await repoApiClient.validate(value);
    if (response.ok) {
      setValidation(response.data);
    }
  }, []);

  const submit = useCallback(
    async (value: string) => {
      setSubmitting(true);
      try {
        const response = await repoApiClient.submit(value);
        if (!response.ok) {
          return;
        }
        const snapshot = await repoApiClient.getSession(response.session_id ?? undefined);
        if (snapshot.ok) {
          dispatch({ type: 'snapshot', snapshot: snapshot.data });
        }
        if (response.session_id) {
          register(
            streamClient.connectAnalysis(response.session_id, (event) =>
              dispatch({ type: 'event', event })
            )
          );
        }
      } finally {
        setSubmitting(false);
      }
    },
    [register]
  );

  const sendMessage = useCallback(
    async (message: string) => {
      if (!store.sessionId) {
        return;
      }
      const response = await chatApiClient.sendMessage(store.sessionId, message);
      if (response.ok) {
        register(
          streamClient.connectChat(store.sessionId, (event) =>
            dispatch({ type: 'event', event })
          )
        );
      }
    },
    [register, store.sessionId]
  );

  const clearSession = useCallback(async () => {
    if (!store.sessionId) {
      return;
    }
    await repoApiClient.clearSession(store.sessionId);
    closeAll();
    dispatch({ type: 'reset' });
  }, [closeAll, store.sessionId]);

  return {
    store,
    inputValue,
    validation,
    submitting,
    setInputValue,
    validate,
    submit,
    sendMessage,
    clearSession
  };
}

