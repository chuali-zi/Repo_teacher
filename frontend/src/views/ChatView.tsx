import { ChatInput } from '../components/ChatInput';
import { ErrorDebugPanel } from '../components/ErrorDebugPanel';
import { MessageList } from '../components/MessageList';
import type { ClientSessionStore } from '../types/contracts';

type ChatViewProps = {
  store: ClientSessionStore;
  onSend(message: string): Promise<void>;
  onClear(): Promise<void>;
};

export function ChatView({ store, onSend, onClear }: ChatViewProps) {
  const disabled = store.status !== 'chatting' || store.subStatus !== 'waiting_user';
  const placeholder = disabled ? 'Agent 正在思考...' : '输入你的问题，或点击上方建议...';

  return (
    <main className="view chat-view">
      <div className="toolbar">
        <h1>{store.repoDisplayName ?? 'Repo Tutor'}</h1>
        <button type="button" onClick={() => void onClear()}>
          切换仓库
        </button>
      </div>
      {store.degradationNotices.length > 0 ? (
        <section className="notice-panel">
          <h2>降级提示</h2>
          <ul className="plain-list">
            {store.degradationNotices.map((notice) => (
              <li key={notice.degradation_id}>{notice.user_notice}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {store.activeError ? <ErrorDebugPanel error={store.activeError} /> : null}
      {disabled && store.activeAgentActivity ? (
        <section className="notice-panel" aria-live="polite">
          <h2>Agent 正在处理</h2>
          <p>{store.activeAgentActivity.summary}</p>
        </section>
      ) : null}
      <MessageList disabled={disabled} messages={store.messages} onPickSuggestion={onSend} />
      <ChatInput disabled={disabled} placeholder={placeholder} onSend={onSend} />
    </main>
  );
}
