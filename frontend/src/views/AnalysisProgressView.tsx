import { MessageList } from '../components/MessageList';
import { ProgressSteps } from '../components/ProgressSteps';
import { ErrorDebugPanel } from '../components/ErrorDebugPanel';
import type { ClientSessionStore } from '../types/contracts';

type AnalysisProgressViewProps = {
  store: ClientSessionStore;
  onClear(): Promise<void>;
};

export function AnalysisProgressView({ store, onClear }: AnalysisProgressViewProps) {
  const timeoutNotice = store.degradationNotices.find((item) => item.type === 'analysis_timeout');

  return (
    <main className="view">
      <div className="toolbar">
        <h1>{store.repoDisplayName ?? '仓库分析中'}</h1>
        <button type="button" onClick={() => void onClear()}>
          切换仓库
        </button>
      </div>
      {store.degradationNotices.length > 0 ? (
        <section className="notice-panel">
          <h2>分析提示</h2>
          <ul className="plain-list">
            {store.degradationNotices.map((notice) => (
              <li key={notice.degradation_id}>{notice.user_notice}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {timeoutNotice ? <p className="warning-text">分析时间较长，正在尝试降级分析...</p> : null}
      <ProgressSteps steps={store.progressSteps} />
      {store.messages.length > 0 ? (
        <MessageList
          disabled={true}
          messages={store.messages}
          onPickSuggestion={ignoreSuggestionPick}
        />
      ) : null}
      {store.activeError ? <ErrorDebugPanel error={store.activeError} /> : null}
    </main>
  );
}

async function ignoreSuggestionPick() {
  return undefined;
}
