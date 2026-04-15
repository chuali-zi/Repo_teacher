import type { UserFacingErrorDto } from '../types/contracts';

type ErrorDebugPanelProps = {
  error: UserFacingErrorDto;
};

export function ErrorDebugPanel({ error }: ErrorDebugPanelProps) {
  return (
    <section className="error-panel">
      <h2>出错了</h2>
      <p>{error.message}</p>
      <dl className="debug-grid">
        <div>
          <dt>错误码</dt>
          <dd>{error.error_code}</dd>
        </div>
        <div>
          <dt>阶段</dt>
          <dd>{error.stage}</dd>
        </div>
        <div>
          <dt>可重试</dt>
          <dd>{error.retryable ? '是' : '否'}</dd>
        </div>
        <div>
          <dt>保留输入</dt>
          <dd>{error.input_preserved ? '是' : '否'}</dd>
        </div>
      </dl>
      {error.internal_detail ? (
        <details className="debug-detail" open>
          <summary>后端详细原因</summary>
          <pre>{error.internal_detail}</pre>
        </details>
      ) : null}
    </section>
  );
}
