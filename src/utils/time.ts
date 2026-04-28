export function getCurrentTimeMs(): number {
  return Date.now();
}

export function getCurrentTimeIso(): string {
  return new Date().toISOString();
}

export function addMs(date: Date, ms: number): Date {
  return new Date(date.getTime() + ms);
}

export function diffMs(start: Date, end: Date): number {
  return end.getTime() - start.getTime();
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const minutes = seconds / 60;
  return `${minutes.toFixed(2)}m`;
}
