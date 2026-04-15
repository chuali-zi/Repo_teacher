import type { ConfidenceLevel, MessageDto, SuggestionDto } from '../types/contracts';
import { hasRenderableMessageText, stripStructuredPayload } from '../utils/messageText';
import { ConfidenceTag } from './ConfidenceTag';
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
  const suggestions = getMessageSuggestions(message);

  if (hasRenderableMessageText(message.raw_text)) {
    const confidence = getMessageConfidence(message);
    return (
      <article className="message agent-message">
        <header className="message-header">
          <span className="message-kicker">{getMessageKicker(message)}</span>
          {confidence ? <ConfidenceTag confidence={confidence} /> : null}
        </header>
        <RawMarkdown text={rawText} />
        {message.error_state ? <p className="error-text">{message.error_state.error.message}</p> : null}
        <SuggestionSection
          disabled={disabled}
          onPick={onPickSuggestion}
          show={showSuggestions}
          suggestions={suggestions}
        />
      </article>
    );
  }

  if (message.initial_report_content) {
    const content = message.initial_report_content;
    return (
      <article className="message agent-message">
        <header className="message-header">
          <span className="message-kicker">首轮教学报告</span>
          <ConfidenceTag confidence={content.overview.confidence} />
        </header>
        <section className="message-section">
          <h3>仓库概览</h3>
          <p>{content.overview.summary}</p>
          <CodeRefList refs={content.overview.evidence_refs} />
        </section>
        <section className="message-section">
          <h3>先抓什么</h3>
          <ul className="plain-list">
            {content.focus_points.map((item) => (
              <li key={`${item.topic}-${item.title}`}>
                <strong>{item.title}</strong>
                <p>{item.reason}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="message-section">
          <h3>当前仓库映射</h3>
          <ul className="plain-list">
            {content.repo_mapping.map((item) => (
              <li key={`${item.concept}-${item.explanation}`}>
                <strong>{item.concept}</strong>
                <p>{item.explanation}</p>
                <CodeRefList refs={item.mapped_paths} />
              </li>
            ))}
          </ul>
        </section>
        <section className="message-section">
          <h3>语言与项目类型</h3>
          <p>主语言：{content.language_and_type.primary_language}</p>
          {content.language_and_type.degradation_notice ? (
            <p className="warning-text">{content.language_and_type.degradation_notice}</p>
          ) : null}
          <ul className="plain-list">
            {content.language_and_type.project_types.map((item) => (
              <li key={`${item.type}-${item.reason}`}>
                <span>{item.type}</span>
                <ConfidenceTag confidence={item.confidence} />
                <p>{item.reason}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="message-section">
          <h3>关键目录</h3>
          <ul className="plain-list">
            {content.key_directories.map((item) => (
              <li key={item.path}>
                <code>{item.path}</code>
                <p>{item.role}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="message-section">
          <h3>入口候选</h3>
          {content.entry_section.entries.length > 0 ? (
            <ul className="plain-list">
              {content.entry_section.entries.map((item) => (
                <li key={item.entry_id}>
                  <code>{item.target_value}</code>
                  <ConfidenceTag confidence={item.confidence} />
                  <p>{item.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p>未找到可靠入口候选。</p>
          )}
          {content.entry_section.fallback_advice ? (
            <p className="subtle-text">{content.entry_section.fallback_advice}</p>
          ) : null}
        </section>
        <section className="message-section">
          <h3>推荐第一步</h3>
          <p>
            <code>{content.recommended_first_step.target}</code>
          </p>
          <p>{content.recommended_first_step.reason}</p>
          <p className="subtle-text">{content.recommended_first_step.learning_gain}</p>
        </section>
        <section className="message-section">
          <h3>阅读路径预览</h3>
          <ol className="plain-list ordered-list">
            {content.reading_path_preview.map((item) => (
              <li key={item.step_no}>
                <strong>{item.step_no}. </strong>
                <code>{item.target}</code>
                <p>{item.reason}</p>
                <p className="subtle-text">学习收益：{item.learning_gain}</p>
              </li>
            ))}
          </ol>
        </section>
        <section className="message-section">
          <h3>不确定项</h3>
          {content.unknown_section.length > 0 ? (
            <ul className="plain-list muted-panel">
              {content.unknown_section.map((item) => (
                <li key={item.unknown_id}>
                  <strong>{item.topic}</strong>
                  <p>{item.description}</p>
                  {item.reason ? <p className="subtle-text">原因：{item.reason}</p> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="subtle-text">当前没有额外不确定项。</p>
          )}
        </section>
        <SuggestionSection
          disabled={disabled}
          onPick={onPickSuggestion}
          show={showSuggestions}
          suggestions={suggestions}
        />
      </article>
    );
  }

  if (message.structured_content) {
    const content = message.structured_content;
    return (
      <article className="message agent-message">
        <header className="message-header">
          <span className="message-kicker">Agent 回答</span>
        </header>
        <section className="message-section">
          <h3>本轮重点</h3>
          <p>{content.focus}</p>
        </section>
        <section className="message-section">
          <h3>直接解释</h3>
          <p>{content.direct_explanation}</p>
        </section>
        <section className="message-section">
          <h3>与整体的关系</h3>
          <p>{content.relation_to_overall}</p>
        </section>
        <section className="message-section">
          <h3>判断依据</h3>
          <ul className="plain-list">
            {content.evidence_lines.map((item, index) => (
              <li key={`${message.message_id}-evidence-${index}`}>
                <p>{item.text}</p>
                <div className="inline-meta">
                  <ConfidenceTag confidence={item.confidence} />
                  <CodeRefList refs={item.evidence_refs} />
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section className="message-section">
          <h3>不确定项</h3>
          <ul className="plain-list muted-panel">
            {content.uncertainties.map((item, index) => (
              <li key={`${message.message_id}-uncertainty-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
        <SuggestionSection
          disabled={disabled}
          onPick={onPickSuggestion}
          show={showSuggestions}
          suggestions={suggestions}
        />
      </article>
    );
  }

  return (
    <article className="message agent-message">
      <header className="message-header">
        <span className="message-kicker">Agent 回答</span>
      </header>
      <RawMarkdown text={stripStructuredPayload(message.raw_text)} />
      {message.error_state ? <p className="error-text">{message.error_state.error.message}</p> : null}
      <SuggestionSection
        disabled={disabled}
        onPick={onPickSuggestion}
        show={showSuggestions}
        suggestions={suggestions}
      />
    </article>
  );
}

function CodeRefList({ refs }: { refs: string[] }) {
  if (refs.length === 0) {
    return null;
  }

  return (
    <div className="code-ref-list">
      {refs.map((ref) => (
        <code key={ref}>{ref}</code>
      ))}
    </div>
  );
}

function getMessageKicker(message: MessageDto) {
  return message.message_type === 'initial_report' ? '首轮教学报告' : 'Agent 回答';
}

function getMessageConfidence(message: MessageDto): ConfidenceLevel | null {
  return message.initial_report_content?.overview.confidence ?? null;
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

  return [];
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
