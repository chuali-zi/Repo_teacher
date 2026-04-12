import type { SuggestionDto } from '../types/contracts';

export type SuggestionButtonsProps = {
  disabled: boolean;
  suggestions: SuggestionDto[];
  onPick(suggestionText: string): Promise<void>;
};

export function SuggestionButtons({
  disabled,
  suggestions,
  onPick
}: SuggestionButtonsProps) {
  return (
    <div className="suggestions">
      {suggestions.slice(0, 3).map((suggestion) => (
        <button
          key={suggestion.suggestion_id}
          disabled={disabled}
          type="button"
          onClick={() => onPick(suggestion.text)}
        >
          {suggestion.text}
        </button>
      ))}
    </div>
  );
}

