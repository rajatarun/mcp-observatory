import { createHash } from 'crypto';

export function hashText(text: string): string {
  return createHash('sha256').update(text).digest('hex');
}

export function hashJson(obj: unknown): string {
  const canonical = JSON.stringify(obj, Object.keys(obj as object).sort());
  return hashText(canonical);
}

export function normalizePrompt(prompt: string): string {
  return prompt
    .toLowerCase()
    .trim()
    .replace(/\s+/g, ' ');
}

export function computePromptHash(prompt: string): string {
  return hashText(normalizePrompt(prompt));
}
