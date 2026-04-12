import type {
  AnalysisSseEvent,
  ChatSseEvent,
  ClearSessionResponse,
  CloseFn,
  GetSessionResponse,
  SendMessageResponse,
  SubmitRepoResponse,
  ValidateRepoResponse
} from './contracts';

export type RepoApiClient = {
  validate(inputValue: string): Promise<ValidateRepoResponse>;
  submit(inputValue: string): Promise<SubmitRepoResponse>;
  getSession(sessionId?: string): Promise<GetSessionResponse>;
  clearSession(sessionId: string): Promise<ClearSessionResponse>;
};

export type ChatApiClient = {
  sendMessage(sessionId: string, message: string): Promise<SendMessageResponse>;
};

export type StreamClient = {
  connectAnalysis(sessionId: string, onEvent: (evt: AnalysisSseEvent) => void): CloseFn;
  connectChat(sessionId: string, onEvent: (evt: ChatSseEvent) => void): CloseFn;
};

export type {
  AnalysisSseEvent,
  ChatSseEvent,
  ClearSessionResponse,
  CloseFn,
  GetSessionResponse,
  SendMessageResponse,
  SubmitRepoResponse,
  ValidateRepoResponse
};

