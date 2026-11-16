export const TXT_EXPORT_MESSAGE = 'yeobaek.export.txt.v1';

export type TxtExport = { type: typeof TXT_EXPORT_MESSAGE; title: string; text: string };

export function parseTxtExport(raw: string): TxtExport | null {
  if (raw.length > 5_000_000) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return null;
    const message = value as Record<string, unknown>;
    if (message.type !== TXT_EXPORT_MESSAGE || typeof message.title !== 'string' || typeof message.text !== 'string') return null;
    if (message.title.length > 200 || message.text.length > 4_000_000) return null;
    return { type: TXT_EXPORT_MESSAGE, title: message.title, text: message.text };
  } catch { return null; }
}

export function txtExportName(title: string, now = new Date()): string {
  const base = title.replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '_').replace(/^[.\s]+|[.\s]+$/gu, '').slice(0, 80) || '원고';
  const stamp = now.toISOString().replace(/[-:TZ.]/g, '').slice(0, 17);
  return `${base}-${stamp}.txt`;
}
