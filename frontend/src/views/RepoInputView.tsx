import { InputField } from '../components/InputField';

export type RepoInputViewProps = {
  inputValue: string;
  validationMessage: string | null;
  submitting: boolean;
  onChange(value: string): void;
  onValidate(value: string): Promise<void>;
  onSubmit(value: string): Promise<void>;
};

export function RepoInputView({
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
          placeholder="C:\\repo\\demo 或 https://github.com/owner/repo"
          value={inputValue}
          onChange={(next) => {
            onChange(next);
            void onValidate(next);
          }}
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
      {validationMessage ? <p className="error-text">{validationMessage}</p> : null}
    </main>
  );
}

