import type { SuggestionDto } from '../types/contracts';

export function stripStructuredPayload(text: string) {
  return text
    .replace(/<json_output>[\s\S]*?<\/json_output>/gi, '')
    .replace(/```json_output[\s\S]*?```/gi, '');
}

export function hasRenderableMessageText(text: string) {
  const visibleText = stripStructuredPayload(text).trim();
  return visibleText.length > 0 && !isPlainJsonPayload(visibleText);
}

function isPlainJsonPayload(text: string) {
  if (!((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']')))) {
    return false;
  }

  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

export function extractSuggestionHints(text: string): SuggestionDto[] {
  const visibleText = stripStructuredPayload(text);
  const lines = visibleText.replace(/\r\n/g, '\n').split('\n');
  const suggestions: SuggestionDto[] = [];
  let collecting = false;

  for (const line of lines) {
    const trimmed = line.trim();
    const headingText = trimmed.replace(/^#{1,6}\s+/, '').trim();

    if (!collecting && isSuggestionHeading(headingText)) {
      collecting = true;
      const inlineText = headingText.replace(/^(?:建议)?下一步(?:建议|可以)?[：:]?/, '').trim();
      addSuggestion(suggestions, inlineText);
      continue;
    }

    if (!collecting) {
      continue;
    }

    if (!trimmed) {
      if (suggestions.length > 0) {
        break;
      }
      continue;
    }

    if (/^#{1,6}\s+/.test(trimmed) && suggestions.length > 0) {
      break;
    }

    const bulletMatch = /^(?:[-*•]|\d+[.)、])\s*(.+)$/.exec(trimmed);
    const candidate = bulletMatch ? bulletMatch[1] : suggestions.length === 0 ? trimmed : '';
    addSuggestion(suggestions, candidate);

    if (suggestions.length >= 3) {
      break;
    }
  }

  return suggestions;
}

function isSuggestionHeading(text: string) {
  return /^(?:建议)?下一步(?:建议|可以)?[：:]?/.test(text);
}

function addSuggestion(suggestions: SuggestionDto[], text: string) {
  const cleaned = text.replace(/^[:：\s-]+/, '').trim();
  if (!cleaned || cleaned.length < 4 || cleaned.length > 120) {
    return;
  }
  if (suggestions.some((item) => item.text === cleaned)) {
    return;
  }
  suggestions.push({
    suggestion_id: `stream_suggestion_${hashText(cleaned)}`,
    text: cleaned,
    target_goal: null
  });
}

function hashText(text: string) {
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) {
    hash = (hash * 31 + text.charCodeAt(index)) >>> 0;
  }
  return hash.toString(36);
}
