import { ApiError, Manuscript } from './api';
export type Draft = { id: string; title: string; body: string; version: number; time: number };
export type DraftStore = { put(draft: Draft): Promise<void>; clear(draft: Draft): Promise<void> };
// Python re \s includes these control characters; JS \s additionally includes BOM.
export const count = (text: string) => Array.from(text.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu, '')).length;
export const koreaDay = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
export class Editor {
  base: Manuscript;
  title: string;
  body: string;
  dirty = false;
  busy = false;
  review = false;
  conflict?: Manuscript;
  message = '저장됨';
  error = '';
  authRequired = false;
  private revision = 0;
  private queue: Promise<void> = Promise.resolve();
  constructor(doc: Manuscript, private store: DraftStore, private send: (doc: Manuscript) => Promise<Manuscript>, private notify: () => void) {
    this.base = doc; this.title = doc.title; this.body = doc.body;
  }
  draft(): Draft { return { id: this.base.id, title: this.title, body: this.body, version: this.base.version, time: Date.now() }; }
  private enqueue(task: () => Promise<void>) {
    this.queue = this.queue.catch(() => {}).then(task);
    return this.queue;
  }
  edit(title: string, body: string) {
    this.title = title; this.body = body; this.dirty = true; this.revision++;
    this.message = this.review ? 'B 확인 중 · 서버 저장 전' : '저장 대기';
    const draft = this.draft();
    void this.enqueue(() => this.store.put(draft)).catch(() => {
      this.error = '기기 임시 저장 실패. 앱을 닫지 말고 공유로 글을 보관해 주세요.'; this.notify();
    });
    this.notify();
  }
  loadRecovery(draft: Draft) {
    this.review = true; this.conflict = undefined;
    this.edit(draft.title, draft.body);
  }
  stats() {
    const total = count(this.body);
    return { total, today: (this.base.day === koreaDay() ? this.base.today : 0) + total - this.base.total };
  }
  async preserve() { await this.enqueue(() => this.store.put(this.draft())); }
  async save(manual = false): Promise<boolean> {
    if (this.busy || this.conflict || (this.review && !manual)) return false;
    if (!this.dirty) return true;
    this.busy = true; this.message = '저장 중…'; this.error = ''; this.notify();
    const draft = this.draft(), revision = this.revision;
    try {
      // Do not send before this edit has a durable recovery copy.
      await this.enqueue(() => this.store.put(draft));
      const saved = await this.send({ ...this.base, title: draft.title, body: draft.body });
      this.base = saved; this.review = false;
      this.dirty = this.revision !== revision;
      if (this.dirty) await this.enqueue(() => this.store.put(this.draft()));
      else await this.enqueue(() => this.store.clear(draft));
      this.message = this.dirty ? '저장 대기' : '저장됨';
      return !this.dirty;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) this.conflict = e.current;
      if (e instanceof ApiError && [401, 403].includes(e.status)) this.authRequired = true;
      this.error = e instanceof Error ? e.message : '저장 실패';
      this.message = this.conflict ? '동시 수정 · 자동저장 중지' : '저장되지 않음 · 다시 저장 필요';
      return false;
    } finally { this.busy = false; this.notify(); }
  }
  async refresh(get: () => Promise<Manuscript>) {
    if (this.dirty || this.busy || this.review) return;
    const revision = this.revision;
    const doc = await get();
    if (this.dirty || this.busy || this.review || revision !== this.revision) return;
    this.base = doc; this.title = doc.title; this.body = doc.body; this.notify();
  }
}
