import type { MessageDto } from '../types/contracts';
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
        {showSuggestions ? (
          <section className="message-section">
            <h3>下一步建议</h3>
            <SuggestionButtons
              disabled={disabled}
              suggestions={content.suggested_next_questions}
              onPick={onPickSuggestion}
            />
          </section>
        ) : null}
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
        {showSuggestions ? (
          <section className="message-section">
            <h3>下一步建议</h3>
            <SuggestionButtons
              disabled={disabled}
              suggestions={content.next_steps}
              onPick={onPickSuggestion}
            />
          </section>
        ) : null}
      </article>
    );
  }

  return (
    <article className="message agent-message">
      <header className="message-header">
        <span className="message-kicker">Agent 回答</span>
      </header>
      <p>{message.raw_text}</p>
      {message.error_state ? <p className="error-text">{message.error_state.error.message}</p> : null}
      {showSuggestions ? (
        <SuggestionButtons
          disabled={disabled}
          suggestions={message.suggestions}
          onPick={onPickSuggestion}
        />
      ) : null}
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
