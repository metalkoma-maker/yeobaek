import type { Draft, DraftStore } from './editor';
type Storage = { getItem(key: string): Promise<string | null>; setItem(key: string, value: string): Promise<void>; removeItem(key: string): Promise<void> };
function decode(raw: string, id: string): Draft {
  const draft = JSON.parse(raw);
  if (draft.id !== id || typeof draft.title !== 'string' || typeof draft.body !== 'string' || !Number.isInteger(draft.version) || draft.version < 0 || !Number.isFinite(draft.time)) throw Error('기기 보관본을 읽지 못했습니다.');
  return draft;
}
export function createDraftStore(storage: Storage, origin: string, email: string): DraftStore & { archive(draft: Draft): Promise<void>; read(id: string): Promise<Draft | null> } {
  const key = (id: string) => 'yeobaek.mobile.draft.v1:' + JSON.stringify([origin, email, id]);
  return {
    async put(draft) { await storage.setItem(key(draft.id), JSON.stringify(draft)); },
    async archive(draft) { await storage.setItem(key(draft.id) + ':recoveryB', JSON.stringify(draft)); },
    async clear(draft) {
      const raw = await storage.getItem(key(draft.id));
      if (!raw) return;
      const old = decode(raw, draft.id);
      if (old.title === draft.title && old.body === draft.body) await storage.removeItem(key(draft.id));
    },
    async read(id) {
      const raw = await storage.getItem(key(id)) ?? await storage.getItem(key(id) + ':recoveryB');
      return raw ? decode(raw, id) : null;
    },
  };
}
