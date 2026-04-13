import { useCallback, useEffect, useReducer, useState } from 'react';

import { chatApiClient, repoApiClient, streamClient } from '../api/client';
import {
  fromSnapshot,
  initialClientSessionStore,
  sessionReducer
} from '../store/sessionStore';
import type {
  SessionSnapshotDto,
  SessionStatus,
  UserFacingErrorDto,
  ValidateRepoData
} from '../types/contracts';
import { useSSE } from './useSSE';

const ANALYSIS_STREAM_KEY = 'analysis';
const CHAT_STREAM_KEY = 'chat';

export function useSession() {
  const [store, dispatch] = useReducer(sessionReducer, initialClientSessionStore);
  const [inputValue, setInputValue] = useState('');
  const [validation, setValidation] = useState<ValidateRepoData | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { register, close, closeAll } = useSSE();

  const syncStreamForSnapshot = useCallback(
    (snapshot: SessionSnapshotDto) => {
      if (!snapshot.session_id) {
        closeAll();
        return;
      }

      const nextStore = fromSnapshot(snapshot);

      if (shouldConnectAnalysis(nextStore.status)) {
        close(CHAT_STREAM_KEY);
        register(
          ANALYSIS_STREAM_KEY,
          streamClient.connectAnalysis(snapshot.session_id, (event) =>
            dispatch({ type: 'event', event })
          )
        );
        return;
      }

      close(ANALYSIS_STREAM_KEY);

      if (nextStore.currentView === 'chat' && nextStore.subStatus !== 'waiting_user') {
        register(
          CHAT_STREAM_KEY,
          streamClient.connectChat(snapshot.session_id, (event) =>
            dispatch({ type: 'event', event })
          )
        );
        return;
      }

      close(CHAT_STREAM_KEY);
    },
    [close, closeAll, register]
  );

  useEffect(() => {
    let cancelled = false;
    repoApiClient.getSession().then((response) => {
      if (!cancelled && response.ok) {
        dispatch({ type: 'snapshot', snapshot: response.data });
        if (response.data.repository?.input_value) {
          setInputValue(response.data.repository.input_value);
        }
        if (response.data.active_error) {
          setValidation(toValidationMessage(response.data.active_error));
        }
        syncStreamForSnapshot(response.data);
      }
    });
    return () => {
      cancelled = true;
      closeAll();
    };
  }, [closeAll, syncStreamForSnapshot]);

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
          setValidation(toValidationMessage(response.error));
          return;
        }
        setValidation(null);
        setInputValue(value);
        const snapshot = await repoApiClient.getSession(response.session_id ?? undefined);
        if (snapshot.ok) {
          dispatch({ type: 'snapshot', snapshot: snapshot.data });
          syncStreamForSnapshot(snapshot.data);
        }
      } finally {
        setSubmitting(false);
      }
    },
    [syncStreamForSnapshot]
  );

  const sendMessage = useCallback(
    async (message: string) => {
      if (!store.sessionId) {
        return;
      }
      const response = await chatApiClient.sendMessage(store.sessionId, message);
      if (response.ok) {
        const snapshot = await repoApiClient.getSession(store.sessionId);
        if (snapshot.ok) {
          dispatch({ type: 'snapshot', snapshot: snapshot.data });
        }
        close(ANALYSIS_STREAM_KEY);
        register(
          CHAT_STREAM_KEY,
          streamClient.connectChat(store.sessionId, (event) =>
            dispatch({ type: 'event', event })
          )
        );
      }
    },
    [close, register, store.sessionId]
  );

  const clearSession = useCallback(async () => {
    if (!store.sessionId) {
      return;
    }
    await repoApiClient.clearSession(store.sessionId);
    setValidation(null);
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

function shouldConnectAnalysis(status: SessionStatus): boolean {
  return status === 'accessing' || status === 'analyzing';
}

function toValidationMessage(error: UserFacingErrorDto): ValidateRepoData {
  return {
    input_kind: 'unknown',
    is_valid: false,
    normalized_input: null,
    message: error.message
  };
}
