import { ProgressSteps } from '../components/ProgressSteps';
import type { ClientSessionStore } from '../types/contracts';

type AnalysisProgressViewProps = {
  store: ClientSessionStore;
  onClear(): Promise<void>;
};

export function AnalysisProgressView({ store, onClear }: AnalysisProgressViewProps) {
  return (
    <main className="view">
      <div className="toolbar">
        <h1>{store.repoDisplayName ?? '仓库分析中'}</h1>
        <button type="button" onClick={() => void onClear()}>
          切换仓库
        </button>
      </div>
      <ProgressSteps steps={store.progressSteps} />
      {store.activeError ? <p className="error-text">{store.activeError.message}</p> : null}
    </main>
  );
}

