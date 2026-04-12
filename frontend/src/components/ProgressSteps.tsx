import type { ProgressStepStateItem } from '../types/contracts';

type ProgressStepsProps = {
  steps: ProgressStepStateItem[];
};

export function ProgressSteps({ steps }: ProgressStepsProps) {
  return (
    <ol className="progress-list">
      {steps.map((step) => (
        <li key={step.step_key} className={`progress-item is-${step.step_state}`}>
          <span>{step.step_key}</span>
          <strong>{step.step_state}</strong>
        </li>
      ))}
    </ol>
  );
}

