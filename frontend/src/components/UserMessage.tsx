import type { MessageDto } from '../types/contracts';

type UserMessageProps = {
  message: MessageDto;
};

export function UserMessage({ message }: UserMessageProps) {
  return <article className="message user-message">{message.raw_text}</article>;
}

