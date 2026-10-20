export type Manuscript = { id: string; title: string; body: string; version: number; updated: number; total: number; today: number; day: string; today_count_rule?: 'with_spaces' | 'without_spaces' };
export type User = { email: string; csrf: string };
export class ApiError extends Error {
  constructor(message: string, public status: number, public current?: Manuscript) { super(message); }
}
export const PRODUCTION_ORIGIN = 'https://yeobaek-write.duckdns.org';
export type ApiMode = 'synthetic' | 'production';
export function buildEndpoint(): { origin: string; mode: ApiMode } {
  const mode = process.env.EXPO_PUBLIC_YEOBAEK_MODE;
  if (mode === 'production') {
    if (process.env.EXPO_PUBLIC_TEST_API_URL) throw Error('운영 앱에 테스트 서버 주소를 함께 설정할 수 없습니다.');
    return { origin: PRODUCTION_ORIGIN, mode };
  }
  if (mode && mode !== 'synthetic') throw Error('알 수 없는 앱 실행 모드입니다.');
  return { origin: process.env.EXPO_PUBLIC_TEST_API_URL || '', mode: 'synthetic' };
}
export function serverAddress(input: string) {
  const url = new URL(input.trim());
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw Error('테스트 서버의 주소만 입력해 주세요.');
  // Personal testing only: never send login or manuscripts to a production host.
  const host = url.hostname;
  const octets = host.split('.').map(Number);
  const ipv4 = /^\d+\.\d+\.\d+\.\d+$/.test(host) && octets.every(n => n >= 0 && n <= 255);
  const privateIP = ipv4 && (octets[0] === 10 || (octets[0] === 192 && octets[1] === 168) || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31));
  const approved = process.env.EXPO_PUBLIC_TEST_API_URL;
  const published = approved && /^https:\/\/(?:[a-z0-9-]+-8000\.app\.github\.dev|[a-z0-9-]+\.trycloudflare\.com)$/.test(approved) && url.origin === approved;
  if (!(host === 'localhost' || host === '127.0.0.1' || privateIP || published)) throw Error('이 앱에 지정된 가짜 원고용 테스트 서버만 사용할 수 있습니다.');
  return url.origin;
}
export class Api {
  csrf = '';
  constructor(public readonly origin: string, public readonly mode: ApiMode = 'synthetic') {
    if (mode === 'production' && origin !== PRODUCTION_ORIGIN) throw Error('운영 서버 주소가 일치하지 않습니다.');
  }
  async request<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(this.origin + '/api' + path, {
        method, credentials: 'include', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrf },
        body: data === undefined ? undefined : JSON.stringify(data),
      });
      const value = await response.json();
      if (!response.ok) throw new ApiError(value.error || '요청에 실패했습니다.', response.status, value.current);
      return value as T;
    } catch (e) {
      if (e instanceof ApiError) throw e;
      throw Error('서버에 연결하지 못했습니다. 입력은 보존됩니다. 인터넷 연결을 확인해 주세요.');
    } finally { clearTimeout(timeout); }
  }
  async login(email: string, password: string) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const path = this.mode === 'production' ? '/__deployment_health__' : '/__mobile_test__';
      const check = await fetch(this.origin + path, { signal: controller.signal, cache: 'no-store' });
      const marker = check.ok ? await check.json() : null;
      const valid = this.mode === 'production'
        ? marker?.api === 'manuscript-order-v1'
        : marker?.syntheticOnly === true && marker?.protocol === 'yeobaek-mobile-test-v1';
      if (!valid) throw Error('서버를 확인하지 못해 로그인을 중단했습니다.');
    } finally { clearTimeout(timer); }
    const user = await this.request<User>('/login', 'POST', { email, password });
    this.csrf = user.csrf;
    return user;
  }
  get(id: string) { return this.request<Manuscript>('/manuscripts/' + id); }
  save(doc: Manuscript) { return this.request<Manuscript>('/manuscripts/' + doc.id, 'PUT', { title: doc.title, body: doc.body, version: doc.version }); }
  checkpoint(id: string, version: number) { return this.request<{ version: number; saved: boolean }>('/manuscripts/' + id + '/session-checkpoint', 'POST', { version }); }
}
