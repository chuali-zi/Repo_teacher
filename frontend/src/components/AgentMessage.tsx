import type { MessageDto } from '../types/contracts';
import { ConfidenceTag } from './ConfidenceTag';

type AgentMessageProps = {
  message: MessageDto;
};

export function AgentMessage({ message }: AgentMessageProps) {
  if (message.initial_report_content) {
    const content = message.initial_report_content;
    return (
      <article className="message agent-message">
        <section>
          <h3>仓库概览</h3>
          <p>{content.overview.summary}</p>
          <ConfidenceTag confidence={content.overview.confidence} />
        </section>
        <section>
          <h3>推荐第一步</h3>
          <p>{content.recommended_first_step.target}</p>
          <p>{content.recommended_first_step.reason}</p>
        </section>
      </article>
    );
  }

  if (message.structured_content) {
    const content = message.structured_content;
    return (
      <article className="message agent-message">
        <h3>{content.focus}</h3>
        <p>{content.direct_explanation}</p>
        <p>{content.relation_to_overall}</p>
      </article>
    );
  }

  return <article className="message agent-message">{message.raw_text}</article>;
}

