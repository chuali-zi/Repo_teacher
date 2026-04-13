import { useState } from 'react';

export type ChatInputProps = {
  disabled: boolean;
  placeholder: string;
  onSend(message: string): Promise<void>;
};

export function ChatInput({ disabled, placeholder, onSend }: ChatInputProps) {
  const [message, setMessage] = useState('');

  const submit = async () => {
    const next = message.trim();
    if (!next || disabled) {
      return;
    }
    setMessage('');
    await onSend(next);
  };

  return (
    <div className="chat-input">
      <textarea
        className="input"
        disabled={disabled}
        placeholder={placeholder}
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void submit();
          }
        }}
      />
      <button disabled={disabled || !message.trim()} type="button" onClick={() => void submit()}>
        发送
      </button>
    </div>
  );
}
