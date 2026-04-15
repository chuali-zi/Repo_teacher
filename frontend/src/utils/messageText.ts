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
