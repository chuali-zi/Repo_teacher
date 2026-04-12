import type {
  AnalysisSseEvent,
  ChatApiClient,
  ChatSseEvent,
  ClearSessionResponse,
  CloseFn,
  GetSessionResponse,
  RepoApiClient,
  SendMessageResponse,
  StreamClient,
  SubmitRepoResponse,
  ValidateRepoResponse
} from '../types/publicApi';

async function requestJson<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...(init.headers ?? {})
    }
  });
  return (await response.json()) as T;
}

export const repoApiClient: RepoApiClient = {
  validate(inputValue: string): Promise<ValidateRepoResponse> {
    return requestJson('/api/repo/validate', {
      method: 'POST',
      body: JSON.stringify({ input_value: inputValue })
    });
  },

  submit(inputValue: string): Promise<SubmitRepoResponse> {
    return requestJson('/api/repo', {
      method: 'POST',
      body: JSON.stringify({ input_value: inputValue })
    });
  },

  getSession(sessionId?: string): Promise<GetSessionResponse> {
    return requestJson('/api/session', {
      method: 'GET',
      headers: sessionId ? { 'X-Session-Id': sessionId } : undefined
    });
  },

  clearSession(sessionId: string): Promise<ClearSessionResponse> {
    return requestJson('/api/session', {
      method: 'DELETE',
      headers: { 'X-Session-Id': sessionId }
    });
  }
};

export const chatApiClient: ChatApiClient = {
  sendMessage(sessionId: string, message: string): Promise<SendMessageResponse> {
    return requestJson('/api/chat', {
      method: 'POST',
      headers: { 'X-Session-Id': sessionId },
      body: JSON.stringify({ message })
    });
  }
};

const analysisEventNames = [
  'status_changed',
  'analysis_progress',
  'degradation_notice',
  'answer_stream_start',
  'answer_stream_delta',
  'answer_stream_end',
  'message_completed',
  'error'
] as const;

const chatEventNames = [
  'status_changed',
  'answer_stream_start',
  'answer_stream_delta',
  'answer_stream_end',
  'message_completed',
  'error'
] as const;

export const streamClient: StreamClient = {
  connectAnalysis(sessionId: string, onEvent: (evt: AnalysisSseEvent) => void): CloseFn {
    const source = new EventSource(`/api/analysis/stream?session_id=${encodeURIComponent(sessionId)}`);
    analysisEventNames.forEach((eventName) => {
      source.addEventListener(eventName, (raw) => onEvent(JSON.parse(raw.data) as AnalysisSseEvent));
    });
    return () => source.close();
  },

  connectChat(sessionId: string, onEvent: (evt: ChatSseEvent) => void): CloseFn {
    const source = new EventSource(`/api/chat/stream?session_id=${encodeURIComponent(sessionId)}`);
    chatEventNames.forEach((eventName) => {
      source.addEventListener(eventName, (raw) => onEvent(JSON.parse(raw.data) as ChatSseEvent));
    });
    return () => source.close();
  }
};

