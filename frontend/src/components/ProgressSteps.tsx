import type { ProgressStepStateItem } from '../types/contracts';

type ProgressStepsProps = {
  steps: ProgressStepStateItem[];
};

export function ProgressSteps({ steps }: ProgressStepsProps) {
  return (
    <ol className="progress-list">
      {steps.map((step) => (
        <li key={step.step_key} className={`progress-item is-${step.step_state}`}>
          <span>{labelForStep(step.step_key)}</span>
          <strong>{labelForState(step.step_state)}</strong>
        </li>
      ))}
    </ol>
  );
}

function labelForStep(stepKey: ProgressStepStateItem['step_key']): string {
  switch (stepKey) {
    case 'repo_access':
      return '仓库接入';
    case 'file_tree_scan':
      return '文件树扫描';
    case 'entry_and_module_analysis':
      return '入口与模块分析';
    case 'dependency_analysis':
      return '依赖分析';
    case 'skeleton_assembly':
      return '骨架组装';
    case 'initial_report_generation':
      return '首轮报告生成';
  }
}

function labelForState(stepState: ProgressStepStateItem['step_state']): string {
  switch (stepState) {
    case 'pending':
      return '等待中';
    case 'running':
      return '进行中';
    case 'done':
      return '已完成';
    case 'error':
      return '失败';
  }
}
