import type { ConfidenceLevel } from '../types/contracts';

type ConfidenceTagProps = {
  confidence: ConfidenceLevel | null;
};

export function ConfidenceTag({ confidence }: ConfidenceTagProps) {
  return <span className="confidence-tag">{confidence ?? 'unknown'}</span>;
}

