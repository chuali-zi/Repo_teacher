import type { MessageDto } from '../types/contracts';
import { AgentMessage } from './AgentMessage';
import { UserMessage } from './UserMessage';

type MessageListProps = {
  messages: MessageDto[];
};

export function MessageList({ messages }: MessageListProps) {
  return (
    <div className="message-list">
      {messages.map((message) =>
        message.role === 'user' ? (
          <UserMessage key={message.message_id} message={message} />
        ) : (
          <AgentMessage key={message.message_id} message={message} />
        )
      )}
    </div>
  );
}

