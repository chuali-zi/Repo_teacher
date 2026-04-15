import { ErrorDebugPanel } from '../components/ErrorDebugPanel';
import { InputField } from '../components/InputField';
import type { UserFacingErrorDto } from '../types/contracts';

export type RepoInputViewProps = {
  activeError: UserFacingErrorDto | null;
  inputValue: string;
  validationMessage: string | null;
  submitting: boolean;
  onChange(value: string): void;
  onValidate(value: string): Promise<void>;
  onSubmit(value: string): Promise<void>;
};

export function RepoInputView({
  activeError,
  inputValue,
  validationMessage,
  submitting,
  onChange,
  onValidate,
  onSubmit
}: RepoInputViewProps) {
  const canSubmit = inputValue.trim().length > 0 && !submitting;

  return (
    <main className="view">
      <h1>读取一个仓库</h1>
      <p>输入本地绝对路径，或公开 GitHub 仓库地址。</p>
      <div className="repo-form">
        <InputField
          disabled={submitting}
          placeholder="输入本地仓库路径或 GitHub 公共仓库 URL"
          value={inputValue}
          onChange={(next) => {
            onChange(next);
            void onValidate(next);
          }}
          onBlur={() => void onValidate(inputValue)}
          onEnter={() => {
            if (canSubmit) {
              void onSubmit(inputValue);
            }
          }}
        />
        <button disabled={!canSubmit} type="button" onClick={() => void onSubmit(inputValue)}>
          开始
        </button>
      </div>
      {activeError ? <ErrorDebugPanel error={activeError} /> : null}
      {!activeError && validationMessage ? <p className="error-text">{validationMessage}</p> : null}
    </main>
  );
}
