import type { ConfidenceLevel } from '../types/contracts';

type ConfidenceTagProps = {
  confidence: ConfidenceLevel | null;
};

export function ConfidenceTag({ confidence }: ConfidenceTagProps) {
  return <span className={`confidence-tag is-${confidence ?? 'unknown'}`}>{labelForConfidence(confidence)}</span>;
}

function labelForConfidence(confidence: ConfidenceLevel | null): string {
  switch (confidence) {
    case 'high':
      return '高';
    case 'medium':
      return '中';
    case 'low':
      return '低';
    default:
      return '未知';
  }
}
