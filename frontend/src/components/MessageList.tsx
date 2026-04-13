import type { MessageDto } from '../types/contracts';
import { AgentMessage } from './AgentMessage';
import { UserMessage } from './UserMessage';

type MessageListProps = {
  disabled: boolean;
  messages: MessageDto[];
  onPickSuggestion(message: string): Promise<void>;
};

export function MessageList({ disabled, messages, onPickSuggestion }: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((message, index) =>
        message.role === 'user' ? (
          <UserMessage key={message.message_id} message={message} />
        ) : (
          <AgentMessage
            key={message.message_id}
            disabled={disabled}
            message={message}
            onPickSuggestion={onPickSuggestion}
            showSuggestions={index === messages.length - 1}
          />
        )
      )}
    </div>
  );
}
