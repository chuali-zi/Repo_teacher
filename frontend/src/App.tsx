import { useSession } from './hooks/useSession';
import { AnalysisProgressView } from './views/AnalysisProgressView';
import { ChatView } from './views/ChatView';
import { RepoInputView } from './views/RepoInputView';

export default function App() {
  const session = useSession();
  const { store } = session;
  const validationMessage =
    session.validation?.is_valid === false
      ? session.validation.message
      : store.currentView === 'input'
        ? store.activeError?.message ?? null
        : null;

  if (store.currentView === 'analysis') {
    return <AnalysisProgressView store={store} onClear={session.clearSession} />;
  }

  if (store.currentView === 'chat') {
    return <ChatView store={store} onClear={session.clearSession} onSend={session.sendMessage} />;
  }

  return (
    <RepoInputView
      inputValue={session.inputValue}
      validationMessage={validationMessage}
      submitting={session.submitting}
      onChange={session.setInputValue}
      onValidate={session.validate}
      onSubmit={session.submit}
    />
  );
}
