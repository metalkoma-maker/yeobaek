import React, { useEffect, useRef, useState } from 'react';
import { Alert, AppState, FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, Share, StyleSheet, Text, TextInput, useWindowDimensions, View } from 'react-native';
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
  const { width } = useWindowDimensions();
  const tablet = width >= 700;
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
  async function checkpointCurrent(candidate = editorRef.current) {
    const client = api.current;
    if (!candidate || !client) return;
    if (candidate.dirty) {
      try { await candidate.preserve(); } catch { setError('기기 임시 저장 실패. 공유로 글을 보관해 주세요.'); return; }
      if (candidate.busy || candidate.review || candidate.conflict || !await candidate.save()) return;
    }
    if (candidate.busy || candidate.dirty || candidate.review || candidate.conflict) return;
    try { await client.checkpoint(candidate.base.id, candidate.base.version); }
    catch { /* Offline and older test servers can retry on the next open. */ }
  }
  useEffect(() => { if (!production && !process.env.EXPO_PUBLIC_TEST_API_URL) void AsyncStorage.getItem('yeobaek.mobile.server').then(v => { if (v) setAddress(v); }).catch(() => {}); }, [production]);
  useEffect(() => {
    let previous = AppState.currentState;
    const subscription = AppState.addEventListener('change', state => {
      setActive(state === 'active');
      if (state !== 'active' || previous !== 'active') void checkpointCurrent();
      previous = state;
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
    const current = editorRef.current;
    if (current?.base.id === id) return;
    if (current && current.base.id !== id) {
      if (current.busy || (current.dirty && !await current.save())) return;
      await checkpointCurrent(current);
    }
    const doc = await api.current!.get(id);
    const store = draftStore(api.current!.origin, user!.email);
    const local = await store.read(id);
    const value = new Editor(doc, store, d => api.current!.save(d), notify);
    attach(value);
    void checkpointCurrent(value);
    if (local && (local.title !== doc.title || local.body !== doc.body)) setComparison({ a: doc, b: local });
  }
  async function list() {
    const current = editorRef.current;
    if (current?.busy) return;
    if (current?.dirty && !await current.save()) return;
    await checkpointCurrent(current);
    await refreshList(); attach(null);
  }
  async function createDoc() {
    const current = editorRef.current;
    if (current?.busy || (current?.dirty && !await current.save())) return;
    await checkpointCurrent(current);
    const doc = await api.current!.request<Manuscript>('/manuscripts', 'POST', {});
    await refreshList();
    await open(doc.id);
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
    await checkpointCurrent(editor);
    await api.current!.request('/logout', 'POST', {});
    attach(null); api.current = null; setUser(null); setDocs([]);
  }
  const stats = editor?.stats();
  const manuscriptList = <View style={[styles.sidebar, tablet && styles.sidebarTablet]}>
    <View style={styles.sidebarHead}><Text style={styles.brand}>소설여백</Text></View>
    <View style={styles.listHeading}><Text style={styles.sectionLabel}>나의 원고</Text><Button label="＋ 새 원고" disabled={busy || !!editor?.busy} onPress={() => void action(createDoc)} /></View>
    <FlatList data={docs} keyExtractor={d => d.id} ListEmptyComponent={<Text style={styles.muted}>새 원고로 이야기를 시작해 보세요.</Text>} renderItem={({ item }) => <Pressable disabled={busy} accessibilityRole="button" onPress={() => void action(() => open(item.id))} style={[styles.listItem, editor?.base.id === item.id && styles.listItemActive]}><Text numberOfLines={1} style={styles.listTitle}>{item.title || '제목 없는 원고'}</Text><Text style={styles.listMeta}>{item.total.toLocaleString()}자 · 최근 수정 {modified(item.updated)}</Text></Pressable>} />
    <View style={styles.account}><Text numberOfLines={1} style={styles.listMeta}>{user?.email}</Text><Pressable onPress={() => void action(logout)} accessibilityRole="button"><Text style={styles.accountAction}>로그아웃</Text></Pressable></View>
  </View>;
  const writingPane = <View style={styles.writing}>
    <View style={styles.toolbar}>{!tablet && <Button label="← 원고 목록" disabled={busy || !!editor?.busy} onPress={() => void action(list)} />}<Text numberOfLines={1} style={styles.saveStatus}>{editor ? editor.message : '원고를 선택해 주세요'}</Text>{!!editor && <Button label="지금 저장" disabled={busy || editor.busy || !editor.dirty} onPress={() => { void editor.save(true); }} />}</View>
    {!editor ? <View style={styles.empty}><Text style={styles.listMeta}>첫 문장을 위한 여백</Text><Text style={styles.emptyTitle}>{'어떤 이야기를\n시작할까요?'}</Text><Button label="새 원고 쓰기" disabled={busy} onPress={() => void action(createDoc)} /></View> : <>
      {!!editor.error && <Text accessibilityRole="alert" style={styles.error}>{editor.error} 입력한 글은 유지됩니다.</Text>}
      {editor.authRequired && <View style={styles.relogin}><Text style={styles.muted}>{user?.email} 계정으로 다시 로그인하세요. 현재 입력은 유지됩니다.</Text><TextInput accessibilityLabel="재로그인 비밀번호" secureTextEntry style={styles.input} value={password} onChangeText={setPassword} /><Button label="다시 로그인" disabled={busy} onPress={() => void action(async () => { await api.current!.login(user!.email, password); setPassword(''); editor.authRequired = false; editor.error = ''; editor.review = true; editor.message = '재로그인됨 · 확인 후 지금 저장'; notify(); })} /></View>}
      {editor.conflict && <Button label="서버 A / 내 글 B 비교" disabled={busy} onPress={() => void action(compare)} />}
      {editor.review && <Button label="이 내용으로 저장" disabled={busy || editor.busy} onPress={() => { void editor.save(true); }} />}
      <View style={[styles.manuscript, tablet && styles.manuscriptTablet]}><TextInput style={styles.title} accessibilityLabel="원고 제목" maxLength={200} editable={!busy && !comparison} value={editor.title} onChangeText={title => editor.edit(title, editor.body)} placeholder="원고 제목" placeholderTextColor="#a0adbb" /><TextInput style={[styles.body, { fontSize: font * 4 / 3, lineHeight: font * 2 }]} accessibilityLabel="원고 본문" multiline textAlignVertical="top" editable={!busy && !comparison} value={editor.body} onChangeText={body => editor.edit(editor.title, body)} placeholder="이야기는 여기서 시작됩니다." placeholderTextColor="#a0adbb" /></View>
      <View style={styles.footer}><Text style={styles.countLabel}>전체 <Text style={styles.countValue}>{stats!.total.toLocaleString()}</Text> 자</Text><Text style={styles.countLabel}>오늘 <Text style={styles.countValue}>{stats!.today > 0 ? '+' : ''}{stats!.today.toLocaleString()}</Text> 자</Text><Text style={styles.countRule}>띄어쓰기 포함 · 줄바꿈 제외 · 한국시간</Text></View>
      <View style={styles.secondary}><View style={styles.fontRow}>{[10,12,14,16,18].map(size => <Pressable key={size} accessibilityRole="button" accessibilityLabel={`본문 ${size}포인트`} accessibilityState={{ selected: font === size }} onPress={() => setFont(size)} style={[styles.size, font === size && styles.sizeSelected]}><Text style={styles.sizeText}>{size}</Text></Pressable>)}</View><Button label="공유 / 글 보관" onPress={() => { void Share.share({ message: editor.title + '\n\n' + editor.body }).catch(() => setError('공유하지 못했습니다.')); }} /><Button label="기기 보관본" disabled={busy || editor.busy} onPress={() => void action(recovery)} /></View>
    </>}
  </View>;
  return <SafeAreaProvider><SafeAreaView style={styles.safe}><StatusBar style="dark" /><KeyboardAvoidingView style={styles.container} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    {!user ? <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.login}>
      <Text style={styles.brand}>소설여백</Text><Text style={styles.brandCaption}>소설 쓰는 공간</Text>
      <Text style={styles.loginTitle}>{'다음 문장을\n이어 쓸 시간.'}</Text>
      <Text style={styles.sectionLabel}>{production ? '소설여백 웹과 같은 계정으로 로그인하세요.' : '테스트 웹과 같은 가짜 계정으로 로그인하세요.'}</Text>
      {production ? <Text style={styles.listMeta}>운영 서버: {endpoint.origin}</Text> : <><Text style={styles.sectionLabel}>테스트 서버 주소</Text><TextInput style={styles.input} accessibilityLabel="테스트 서버 주소" value={address} onChangeText={setAddress} /></>}
      <Text style={styles.sectionLabel}>이메일</Text><TextInput style={styles.input} accessibilityLabel="이메일" autoCapitalize="none" autoCorrect={false} keyboardType="email-address" value={email} onChangeText={setEmail} />
      <Text style={styles.sectionLabel}>비밀번호</Text><TextInput style={styles.input} accessibilityLabel="비밀번호" secureTextEntry value={password} onChangeText={setPassword} />
      <Button label={busy ? '로그인 중…' : '로그인'} disabled={busy} onPress={() => void action(login)} />
      {!production && <Text style={styles.listMeta}>테스트 계정: mobile-test@example.com / test-password-123. 실제 계정이나 원고를 입력하지 마세요.</Text>}
    </ScrollView> : <View style={[styles.workspace, tablet && styles.workspaceTablet]}>{(tablet || !editor) && manuscriptList}{(tablet || !!editor) && writingPane}</View>}
    <Modal visible={!!comparison} animationType="slide" onRequestClose={() => setComparison(null)}><SafeAreaView style={styles.safe}>
      <Text style={styles.heading}>서버 A와 기기 B 비교</Text><Text style={styles.muted}>B 불러오기는 화면에만 반영됩니다. 확인 후 ‘이 내용으로 저장’을 눌러 주세요.</Text>
      <ScrollView>{comparison && [['A · 서버에 저장된 글', comparison.a], ['B · 이 기기에 남은 글', comparison.b]].map(([label, data]) => { const doc = data as Draft; return <View key={label as string} style={styles.doc}><Text style={styles.docTitle}>{label as string}</Text><Text>{doc.title}</Text><Text selectable style={styles.preview}>{doc.body || '(빈 원고)'}</Text></View>; })}</ScrollView>
      <Button label="A 유지하기 · B는 기기에 보관" disabled={busy} onPress={() => void action(() => choose(false))} /><Button label="B 불러오기 · 아직 서버 저장 안 함" disabled={busy} onPress={() => void action(() => choose(true))} /><Button label="닫기" disabled={busy} onPress={() => setComparison(null)} />
    </SafeAreaView></Modal>
  </KeyboardAvoidingView></SafeAreaView></SafeAreaProvider>;
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#fff' }, container: { flex: 1 },
  workspace: { flex: 1 }, workspaceTablet: { flexDirection: 'row' },
  sidebar: { flex: 1, backgroundColor: '#f3f6fa', paddingHorizontal: 18, paddingTop: 24 },
  sidebarTablet: { flex: 0, width: 272, borderRightWidth: 1, borderColor: '#e1e7ee' },
  sidebarHead: { paddingHorizontal: 8 }, brand: { fontFamily: 'Georgia', fontSize: 29, fontWeight: '700', letterSpacing: -1, color: '#172b44' }, brandCaption: { fontSize: 14, letterSpacing: 1, color: '#718096' },
  listHeading: { marginTop: 36, marginBottom: 15, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, sectionLabel: { fontSize: 14, color: '#64758b' },
  listItem: { padding: 15, borderRadius: 8, marginBottom: 5 }, listItemActive: { backgroundColor: '#fff' }, listTitle: { fontSize: 16, color: '#172b44', fontWeight: '500' }, listMeta: { fontSize: 12, color: '#718096', marginTop: 6 },
  account: { borderTopWidth: 1, borderColor: '#dfe6ee', padding: 15, gap: 10 }, accountAction: { color: '#172b44', fontSize: 14 },
  writing: { flex: 1, minWidth: 0, backgroundColor: '#fff' }, toolbar: { minHeight: 64, paddingHorizontal: 16, borderBottomWidth: 1, borderColor: '#edf0f5', flexDirection: 'row', alignItems: 'center', gap: 8 }, saveStatus: { flex: 1, color: '#718096', fontSize: 13 },
  manuscript: { flex: 1, paddingHorizontal: 24, paddingTop: 22 }, manuscriptTablet: { width: '100%', maxWidth: 820, alignSelf: 'center', paddingHorizontal: 50, paddingTop: 42 },
  title: { fontSize: 26, fontWeight: '600', color: '#172b44', paddingVertical: 12 }, body: { flex: 1, color: '#27384c', paddingTop: 20, paddingBottom: 12 },
  footer: { minHeight: 62, borderTopWidth: 1, borderColor: '#edf0f5', flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 18, paddingHorizontal: 20, paddingVertical: 10 },
  countLabel: { fontSize: 14, color: '#718096' }, countValue: { fontSize: 20, fontWeight: '600', color: '#172b44' }, countRule: { color: '#718096', fontSize: 12 },
  secondary: { borderTopWidth: 1, borderColor: '#edf0f5', flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6, paddingHorizontal: 12 }, fontRow: { flexDirection: 'row', gap: 4 }, size: { padding: 8, borderRadius: 6 }, sizeSelected: { backgroundColor: '#e8eef5' }, sizeText: { color: '#172b44', fontSize: 12 },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 }, emptyTitle: { textAlign: 'center', color: '#172b44', fontSize: 32, lineHeight: 48, marginVertical: 25 },
  login: { width: '100%', maxWidth: 440, alignSelf: 'center', gap: 12, padding: 32, paddingTop: 48 }, loginTitle: { color: '#172b44', fontSize: 38, lineHeight: 52, marginTop: 38, marginBottom: 15 },
  input: { borderWidth: 1, borderColor: '#cfd8e3', borderRadius: 8, padding: 12, backgroundColor: '#fff', color: '#172b44', fontSize: 16 }, relogin: { padding: 16 },
  button: { borderWidth: 1, borderColor: '#dce3eb', backgroundColor: '#fff', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 9, marginVertical: 4 }, buttonText: { color: '#172b44', fontSize: 13 },
  heading: { fontSize: 22, marginVertical: 18, color: '#172b44' }, muted: { color: '#718096', fontSize: 13, marginVertical: 5 },
  error: { backgroundColor: '#fff1df', color: '#973c29', padding: 10, marginVertical: 5 },
  doc: { padding: 16, backgroundColor: '#fff', borderBottomWidth: 1, borderColor: '#e3e0d6' }, docTitle: { fontSize: 18, fontWeight: '600', marginBottom: 8 }, preview: { marginTop: 12, lineHeight: 24 },
});
