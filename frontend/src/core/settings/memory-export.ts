export function createMemoryExportFileName(
  lastUpdated?: string,
  now = new Date(),
): string {
  const timestamp = (lastUpdated ?? now.toISOString()).replace(/[:.]/g, "-");
  return `devpilot-memory-${timestamp}.json`;
}
