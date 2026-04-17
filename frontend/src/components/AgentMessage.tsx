import type { MessageDto, SuggestionDto } from '../types/contracts';
import {
  extractSuggestionHints,
  hasRenderableMessageText,
  stripStructuredPayload
} from '../utils/messageText';
import { ErrorDebugPanel } from './ErrorDebugPanel';
import { SuggestionButtons } from './SuggestionButtons';

type AgentMessageProps = {
  disabled: boolean;
  message: MessageDto;
  onPickSuggestion(message: string): Promise<void>;
  showSuggestions: boolean;
};

export function AgentMessage({
  disabled,
  message,
  onPickSuggestion,
  showSuggestions
}: AgentMessageProps) {
  const rawText = stripStructuredPayload(message.raw_text).trim();
  const hasText = hasRenderableMessageText(message.raw_text);
  const suggestions = getMessageSuggestions(message);

  return (
    <article className="message agent-message">
      <header className="message-header">
        <span className="message-kicker">{getMessageKicker(message)}</span>
      </header>
      {hasText ? (
        <RawMarkdown text={rawText} />
      ) : (
        <p className="subtle-text">本轮回答正文为空，请重试或点击下方建议继续。</p>
      )}
      {message.error_state ? <ErrorDebugPanel error={message.error_state.error} /> : null}
      <SuggestionSection
        disabled={disabled}
        onPick={onPickSuggestion}
        show={showSuggestions}
        suggestions={suggestions}
      />
    </article>
  );
}

function getMessageKicker(message: MessageDto) {
  return message.message_type === 'initial_report' ? '首轮教学报告' : 'Agent 回答';
}

function getMessageSuggestions(message: MessageDto): SuggestionDto[] {
  if (message.suggestions.length > 0) {
    return message.suggestions;
  }

  if (message.initial_report_content?.suggested_next_questions.length) {
    return message.initial_report_content.suggested_next_questions;
  }

  if (message.structured_content?.next_steps.length) {
    return message.structured_content.next_steps;
  }

  return extractSuggestionHints(message.raw_text);
}

function SuggestionSection({
  disabled,
  onPick,
  show,
  suggestions
}: {
  disabled: boolean;
  onPick(suggestionText: string): Promise<void>;
  show: boolean;
  suggestions: SuggestionDto[];
}) {
  if (!show || suggestions.length === 0) {
    return null;
  }

  return (
    <section className="message-section">
      <h3>下一步建议</h3>
      <SuggestionButtons disabled={disabled} suggestions={suggestions} onPick={onPick} />
    </section>
  );
}

type MarkdownBlock =
  | {
      text: string;
      type: 'code';
    }
  | {
      depth: number;
      text: string;
      type: 'heading';
    }
  | {
      lines: string[];
      type: 'paragraph';
    }
  | {
      items: string[];
      type: 'ol' | 'ul';
    };

function RawMarkdown({ text }: { text: string }) {
  const blocks = parseMarkdownBlocks(text);

  if (blocks.length === 0) {
    return null;
  }

  return (
    <div className="raw-markdown">
      {blocks.map((block, index) => {
        if (block.type === 'code') {
          return (
            <pre key={`code-${index}`}>
              <code>{block.text}</code>
            </pre>
          );
        }

        if (block.type === 'heading') {
          const HeadingTag: 'h3' | 'h4' = block.depth <= 2 ? 'h3' : 'h4';
          return (
            <HeadingTag key={`heading-${index}`}>
              <MarkdownInline text={block.text} />
            </HeadingTag>
          );
        }

        if (block.type === 'ul') {
          return (
            <ul key={`ul-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`ul-${index}-${itemIndex}`}>
                  <MarkdownInline text={item} />
                </li>
              ))}
            </ul>
          );
        }

        if (block.type === 'ol') {
          return (
            <ol key={`ol-${index}`}>
              {block.items.map((item, itemIndex) => (
                <li key={`ol-${index}-${itemIndex}`}>
                  <MarkdownInline text={item} />
                </li>
              ))}
            </ol>
          );
        }

        if (block.type === 'paragraph') {
          return (
            <p key={`paragraph-${index}`}>
              <MarkdownInline text={block.lines.join(' ')} />
            </p>
          );
        }

        return null;
      })}
    </div>
  );
}

function MarkdownInline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`)/g).map((part, index) => {
        if (part.length > 1 && part.startsWith('`') && part.endsWith('`')) {
          return <code key={`code-${index}`}>{part.slice(1, -1)}</code>;
        }

        return <span key={`text-${index}`}>{part}</span>;
      })}
    </>
  );
}

function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let codeLines: string[] | null = null;
  let paragraphLines: string[] = [];
  let listBlock: Extract<MarkdownBlock, { type: 'ol' | 'ul' }> | null = null;

  const flushParagraph = () => {
    if (paragraphLines.length > 0) {
      blocks.push({ lines: paragraphLines, type: 'paragraph' });
      paragraphLines = [];
    }
  };

  const flushList = () => {
    if (listBlock) {
      blocks.push(listBlock);
      listBlock = null;
    }
  };

  for (const line of lines) {
    const trimmedLine = line.trim();

    if (trimmedLine.startsWith('```')) {
      if (codeLines) {
        blocks.push({ text: codeLines.join('\n'), type: 'code' });
        codeLines = null;
      } else {
        flushParagraph();
        flushList();
        codeLines = [];
      }
      continue;
    }

    if (codeLines) {
      codeLines.push(line);
      continue;
    }

    if (!trimmedLine) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = /^(#{1,6})\s+(.+)$/.exec(trimmedLine);
    if (headingMatch) {
      flushParagraph();
      flushList();
      blocks.push({
        depth: headingMatch[1].length,
        text: headingMatch[2],
        type: 'heading'
      });
      continue;
    }

    const unorderedMatch = /^\s*[-*]\s+(.+)$/.exec(line);
    if (unorderedMatch) {
      flushParagraph();
      if (listBlock?.type !== 'ul') {
        flushList();
        listBlock = { items: [], type: 'ul' };
      }
      listBlock.items.push(unorderedMatch[1]);
      continue;
    }

    const orderedMatch = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (orderedMatch) {
      flushParagraph();
      if (listBlock?.type !== 'ol') {
        flushList();
        listBlock = { items: [], type: 'ol' };
      }
      listBlock.items.push(orderedMatch[1]);
      continue;
    }

    flushList();
    paragraphLines.push(trimmedLine);
  }

  if (codeLines) {
    blocks.push({ text: codeLines.join('\n'), type: 'code' });
  }
  flushParagraph();
  flushList();

  return blocks;
}
