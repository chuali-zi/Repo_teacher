import { ChatInput } from '../components/ChatInput';
import { MessageList } from '../components/MessageList';
import { SuggestionButtons } from '../components/SuggestionButtons';
import type { ClientSessionStore, SuggestionDto } from '../types/contracts';

type ChatViewProps = {
  store: ClientSessionStore;
  onSend(message: string): Promise<void>;
  onClear(): Promise<void>;
};

export function ChatView({ store, onSend, onClear }: ChatViewProps) {
  const disabled = store.status !== 'chatting' || store.subStatus !== 'waiting_user';
  const suggestions = latestSuggestions(store.messages);

  return (
    <main className="view chat-view">
      <div className="toolbar">
        <h1>{store.repoDisplayName ?? 'Repo Tutor'}</h1>
        <button type="button" onClick={() => void onClear()}>
          切换仓库
        </button>
      </div>
      <MessageList messages={store.messages} />
      <SuggestionButtons disabled={disabled} suggestions={suggestions} onPick={onSend} />
      <ChatInput disabled={disabled} placeholder="继续问这个仓库" onSend={onSend} />
    </main>
  );
}

function latestSuggestions(messages: { suggestions: SuggestionDto[] }[]): SuggestionDto[] {
  const last = [...messages].reverse().find((message) => message.suggestions.length > 0);
  return last?.suggestions.slice(0, 3) ?? [];
}

