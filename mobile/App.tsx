import React, { useEffect, useRef, useState } from 'react';
import { Alert, AppState, FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Share, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Api, buildEndpoint, Manuscript, serverAddress, User } from './src/api';
import { Draft, Editor } from './src/editor';
import { draftStore } from './src/drafts';
const modified = (seconds: number) => new Date(seconds * 1000).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
function Button({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={[styles.button, disabled && { opacity: .4 }]}><Text style={styles.buttonText}>{label}</Text></Pressable>;
}
export default function App() {
  const endpoint = buildEndpoint();
  const production = endpoint.mode === 'production';
  const [address, setAddress] = useState(endpoint.origin);
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [user, setUser] = useState<User | null>(null); const api = useRef<Api | null>(null);
  const [docs, setDocs] = useState<Manuscript[]>([]); const [editor, setEditor] = useState<Editor | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const [, redraw] = useState(0); const notify = () => redraw(n => n + 1);
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [comparison, setComparison] = useState<{ a: Manuscript; b: Draft } | null>(null);
  const [font, setFont] = useState(12); const [active, setActive] = useState(true);
  const lock = useRef(false);
  useEffect(() => { if (!production && !process.env.EXPO_PUBLIC_TEST_API_URL) void AsyncStorage.getItem('yeobaek.mobile.server').then(v => { if (v) setAddress(v); }).catch(() => {}); }, [production]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      setActive(state === 'active');
      if (state !== 'active' && editorRef.current?.dirty) void editorRef.current.preserve().catch(() => { setError('기기 임시 저장 실패. 공유로 글을 보관해 주세요.'); });
    });
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    if (!editor || !active || !editor.dirty || editor.busy || editor.conflict || editor.review || editor.error || comparison) return;
    const timer = setTimeout(() => { void editor.save(); }, 700);
    return () => clearTimeout(timer);
  });
  async function refreshList() { if (api.current) setDocs(await api.current.request<Manuscript[]>('/manuscripts')); }
  useEffect(() => {
    if (!user || !active) return;
    let refreshing = false;
    const timer = setInterval(async () => {
      if (refreshing || lock.current || comparison) return;
      refreshing = true;
      try {
        const current = editorRef.current;
        if (current) await current.refresh(() => api.current!.get(current.base.id));
        else await refreshList();
      } catch { /* Offline inputs remain untouched. Explicit refresh reports errors. */ }
      finally { refreshing = false; }
    }, 10000);
    return () => clearInterval(timer);
  }, [user, active, comparison]);
  async function action(task: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await task(); } catch (e) { setError(e instanceof Error ? e.message : '요청 실패'); }
    finally { lock.current = false; setBusy(false); }
  }
  function attach(value: Editor | null) { editorRef.current = value; setEditor(value); }
  async function login() {
    const client = production ? new Api(endpoint.origin, 'production') : new Api(serverAddress(address));
    const signedIn = await client.login(email, password);
    const list = await client.request<Manuscript[]>('/manuscripts');
    api.current = client; setUser(signedIn); setDocs(list); setPassword('');
    if (!production) await AsyncStorage.setItem('yeobaek.mobile.server', client.origin);
  }
  async function open(id: string) {
    const doc = await api.current!.get(id);
    const store = draftStore(api.current!.origin, user!.email);
    const local = await store.read(id);
    const value = new Editor(doc, store, d => api.current!.save(d), notify);
    attach(value);
    if (local && (local.title !== doc.title || local.body !== doc.body)) setComparison({ a: doc, b: local });
  }
  async function list() {
    const current = editorRef.current;
    if (current?.busy) return;
    if (current?.dirty && !await current.save()) return;
    await refreshList(); attach(null);
  }
  async function compare() {
    if (!editor || editor.busy) return;
    await editor.preserve();
    const a = await api.current!.get(editor.base.id);
    setComparison({ a, b: editor.draft() });
  }
  async function choose(load: boolean) {
    if (!comparison || !editor) return;
    const { a, b } = comparison;
    // Keep B on disk even when displaying A; it stays available via comparison.
    if (editor.dirty) await editor.preserve();
    await draftStore(api.current!.origin, user!.email).archive(b);
    const value = new Editor(a, draftStore(api.current!.origin, user!.email), d => api.current!.save(d), notify);
    if (load) value.loadRecovery(b);
    attach(value); setComparison(null);
  }
  async function recovery() {
    if (!editor || editor.busy) return;
    if (editor.dirty) { await compare(); return; }
    const local = await draftStore(api.current!.origin, user!.email).read(editor.base.id);
    if (!local) { Alert.alert('기기 보관본', '복구할 글이 없습니다.'); return; }
    setComparison({ a: await api.current!.get(editor.base.id), b: local });
  }
  async function logout() {
    if (editor?.busy || (editor?.dirty && !await editor.save())) return;
    await api.current!.request('/logout', 'POST', {});
    attach(null); api.current = null; setUser(null); setDocs([]);
  }
  const stats = editor?.stats();
  return <SafeAreaProvider><SafeAreaView style={styles.safe}><StatusBar style="dark" /><KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    <View style={styles.header}><Text style={styles.brand}>소설여백</Text><Text style={styles.muted}>{production ? '아이폰 앱 · 운영 계정' : '아이폰 테스트 · 가짜 원고 전용'}</Text></View>
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    {!user ? <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.login}>
      <Text style={styles.heading}>글을 이어 쓰는 작은 공간</Text>
      <Text style={styles.muted}>{production ? '소설여백 웹과 같은 계정으로 로그인하세요.' : '테스트 웹과 같은 가짜 계정으로 로그인하세요.'}</Text>
      {production ? <Text style={styles.muted}>운영 서버: {endpoint.origin}</Text> : <><Text>테스트 서버 주소</Text><TextInput style={styles.input} accessibilityLabel="테스트 서버 주소" placeholder="http://192.168.0.10:8000" autoCapitalize="none" keyboardType="url" value={address} onChangeText={setAddress} /></>}
      <Text>이메일</Text><TextInput style={styles.input} accessibilityLabel="이메일" autoCapitalize="none" autoCorrect={false} keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Text>비밀번호</Text><TextInput style={styles.input} accessibilityLabel="비밀번호" secureTextEntry value={password} onChangeText={setPassword} />
      <Button label={busy ? '로그인 중…' : '로그인'} disabled={busy} onPress={() => void action(login)} />
      {!production && <Text style={styles.muted}>테스트 계정: mobile-test@example.com / test-password-123. 실제 계정이나 원고를 입력하지 마세요.</Text>}
    </ScrollView> : !editor ? <View style={styles.container}>
      <Text style={styles.muted}>{user.email}</Text><Text style={styles.heading}>내 원고</Text>
      <View style={styles.row}><Button label="새 원고" disabled={busy} onPress={() => void action(async () => { const d = await api.current!.request<Manuscript>('/manuscripts', 'POST', {}); await refreshList(); await open(d.id); })} /><Button label="새로고침" disabled={busy} onPress={() => void action(refreshList)} /><Button label="로그아웃" disabled={busy} onPress={() => void action(logout)} /></View>
      <FlatList data={docs} keyExtractor={d => d.id} ListEmptyComponent={<Text style={styles.muted}>{production ? '새 원고를 만들어 글을 시작하세요.' : '새 원고로 가짜 글을 작성해 보세요.'}</Text>} renderItem={({ item }) => <Pressable disabled={busy} accessibilityRole="button" onPress={() => void action(() => open(item.id))} style={styles.doc}><Text style={styles.docTitle}>{item.title || '제목 없는 원고'}</Text><Text style={styles.muted}>{item.total.toLocaleString()}자 · 오늘 {item.today > 0 ? '+' : ''}{item.today}자</Text><Text style={styles.muted}>최근 수정 {modified(item.updated)}</Text></Pressable>} />
    </View> : <View style={styles.container}>
      <View style={styles.row}><Button label="목록" disabled={busy || editor.busy} onPress={() => void action(list)} /><Button label="공유 / 글 보관" onPress={() => { void Share.share({ message: editor.title + '\n\n' + editor.body }).catch(() => setError('공유하지 못했습니다.')); }} /><Button label="기기 보관본" disabled={busy || editor.busy} onPress={() => void action(recovery)} /></View>
      <Text style={styles.muted}>{editor.message} · 최근 수정 {modified(editor.base.updated)}</Text>
      {!!editor.error && <Text accessibilityRole="alert" style={styles.error}>{editor.error} 입력한 글은 유지됩니다.</Text>}
      {editor.authRequired && <View><Text style={styles.muted}>{user.email} 계정으로 다시 로그인하세요. 현재 입력은 유지됩니다.</Text><TextInput accessibilityLabel="재로그인 비밀번호" secureTextEntry style={styles.input} value={password} onChangeText={setPassword} /><Button label="다시 로그인" disabled={busy} onPress={() => void action(async () => { await api.current!.login(user.email, password); setPassword(''); editor.authRequired = false; editor.error = ''; editor.review = true; editor.message = '재로그인됨 · 확인 후 지금 저장'; notify(); })} /></View>}
      {editor.conflict ? <Button label="서버 A / 내 글 B 비교" disabled={busy} onPress={() => void action(compare)} /> : <Button label={editor.review ? '이 내용으로 저장' : '지금 저장 / 다시 저장'} disabled={busy || editor.busy || !editor.dirty} onPress={() => { void editor.save(true); }} />}
      <View style={styles.row}><Text>전체 {stats!.total.toLocaleString()}자</Text><Text>오늘 {stats!.today > 0 ? '+' : ''}{stats!.today.toLocaleString()}자</Text></View>
      <Text style={styles.muted}>공백 제외 · 한국시간 · 저장 대기 중 입력 포함</Text>
      <View style={styles.row}>{[10,12,14,16,18].map(size => <Pressable key={size} accessibilityRole="button" accessibilityLabel={`본문 ${size}포인트`} accessibilityState={{ selected: font === size }} onPress={() => setFont(size)} style={styles.size}><Text style={{ fontWeight: font === size ? 'bold' : 'normal' }}>{size}pt</Text></Pressable>)}</View>
      <TextInput style={[styles.input, styles.title]} accessibilityLabel="원고 제목" maxLength={200} editable={!busy && !comparison} value={editor.title} onChangeText={title => editor.edit(title, editor.body)} placeholder="원고 제목" />
      <TextInput style={[styles.body, { fontSize: font * 4 / 3, lineHeight: font * 2 }]} accessibilityLabel="원고 본문" multiline textAlignVertical="top" editable={!busy && !comparison} value={editor.body} onChangeText={body => editor.edit(editor.title, body)} placeholder="이곳에서 이야기를 시작하세요." />
    </View>}
    <Modal visible={!!comparison} animationType="slide" onRequestClose={() => setComparison(null)}><SafeAreaView style={styles.safe}>
      <Text style={styles.heading}>서버 A와 기기 B 비교</Text><Text style={styles.muted}>B 불러오기는 화면에만 반영됩니다. 확인 후 ‘이 내용으로 저장’을 눌러 주세요.</Text>
      <ScrollView>{comparison && [['A · 서버에 저장된 글', comparison.a], ['B · 이 기기에 남은 글', comparison.b]].map(([label, data]) => { const doc = data as Draft; return <View key={label as string} style={styles.doc}><Text style={styles.docTitle}>{label as string}</Text><Text>{doc.title}</Text><Text selectable style={styles.preview}>{doc.body || '(빈 원고)'}</Text></View>; })}</ScrollView>
      <Button label="A 유지하기 · B는 기기에 보관" disabled={busy} onPress={() => void action(() => choose(false))} /><Button label="B 불러오기 · 아직 서버 저장 안 함" disabled={busy} onPress={() => void action(() => choose(true))} /><Button label="닫기" disabled={busy} onPress={() => setComparison(null)} />
    </SafeAreaView></Modal>
  </KeyboardAvoidingView></SafeAreaView></SafeAreaProvider>;
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#faf8f3', padding: 16 }, container: { flex: 1 },
  header: { marginBottom: 18 }, brand: { fontSize: 30, fontWeight: '600', color: '#39483d' }, heading: { fontSize: 22, marginVertical: 18, color: '#30362e' },
  muted: { color: '#66695f', fontSize: 13, marginVertical: 5 }, login: { gap: 12, paddingBottom: 30 },
  input: { borderWidth: 1, borderColor: '#d8d9ce', borderRadius: 8, padding: 12, backgroundColor: '#fff', color: '#272e25', fontSize: 16 }, title: { marginVertical: 10 },
  body: { flex: 1, backgroundColor: '#fffdf8', padding: 12, color: '#272e25', borderRadius: 8 },
  button: { backgroundColor: '#e7ecdf', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 12, marginVertical: 4 }, buttonText: { color: '#35432f', fontWeight: '600' },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' }, size: { padding: 10 },
  error: { backgroundColor: '#fff0e7', color: '#973c29', padding: 10, marginVertical: 5 },
  doc: { padding: 16, backgroundColor: '#fffdf8', borderBottomWidth: 1, borderColor: '#e3e0d6' }, docTitle: { fontSize: 18, fontWeight: '600', marginBottom: 8 }, preview: { marginTop: 12, lineHeight: 24 },
});
