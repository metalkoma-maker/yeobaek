import React, { useRef, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system/legacy';
import { PRODUCTION_ORIGIN } from './api';
import { parseTxtExport, txtExportName } from './webExport';

export function WebTrial({ onBack }: { onBack: () => void }) {
  const [failed, setFailed] = useState(false);
  const exporting = useRef(false);
  const webView = useRef<WebView>(null);
  async function revealLegacyDrafts() {
    try {
      const keys = await AsyncStorage.getAllKeys();
      const available = keys.some(key => key.startsWith('yeobaek.mobile.draft.v1:'));
      webView.current?.injectJavaScript(`window.YeobaekNativeLegacyDrafts = ${available}; window.dispatchEvent(new Event('yeobaek-native-ready')); true;`);
    } catch { /* The web screen stays usable if native storage cannot be read. */ }
  }
  async function exportTxt(raw: string, sourceUrl: string) {
    if (exporting.current || !sourceUrl.startsWith(PRODUCTION_ORIGIN + '/')) return;
    const message = parseTxtExport(raw);
    if (!message) return;
    exporting.current = true;
    try {
      if (!FileSystem.documentDirectory) throw Error('문서 폴더에 접근할 수 없습니다.');
      const filename = txtExportName(message.title);
      await FileSystem.writeAsStringAsync(FileSystem.documentDirectory + encodeURIComponent(filename), message.text, { encoding: 'utf8' });
      Alert.alert('TXT 저장 완료', `파일 앱 > 나의 iPad/iPhone > 소설여백에서 ${filename} 파일을 확인하세요.`);
    } catch {
      Alert.alert('TXT 저장 실패', '파일을 저장하지 못했습니다. 화면의 글은 그대로 있습니다. 다시 시도해 주세요.');
    } finally { exporting.current = false; }
  }
  const confirmBack = () => Alert.alert('기존 화면 열기', '웹 화면의 저장 상태를 먼저 확인해 주세요. 웹 화면과 기존 화면의 기기 보관본은 서로 다릅니다.', [
    { text: '계속 쓰기', style: 'cancel' },
    { text: '기존 화면 열기', onPress: onBack },
  ]);
  function handleMessage(raw: string, sourceUrl: string) {
    if (!sourceUrl.startsWith(PRODUCTION_ORIGIN + '/')) return;
    try { if (JSON.parse(raw)?.type === 'yeobaek.open-legacy.v1') { confirmBack(); return; } } catch {}
    void exportTxt(raw, sourceUrl);
  }
  return <SafeAreaView style={styles.root}>
    {failed && <View style={styles.failure}><Text accessibilityRole="alert" style={styles.error}>웹 화면을 열지 못했습니다. 인터넷을 켠 뒤 다시 시도해 주세요.</Text><View style={styles.failureActions}><Pressable accessibilityRole="button" onPress={() => webView.current?.reload()} style={styles.retry}><Text style={styles.actionText}>다시 시도</Text></Pressable><Pressable accessibilityRole="button" onPress={confirmBack} style={styles.retry}><Text style={styles.actionText}>기존 화면 열기</Text></Pressable></View></View>}
    <WebView
      ref={webView}
      source={{ uri: PRODUCTION_ORIGIN }}
      originWhitelist={[PRODUCTION_ORIGIN]}
      javaScriptEnabled
      domStorageEnabled
      incognito={false}
      sharedCookiesEnabled={false}
      injectedJavaScriptBeforeContentLoaded="window.YeobaekNativeExport = { version: 1 }; true;"
      onMessage={event => handleMessage(event.nativeEvent.data, event.nativeEvent.url)}
      onLoadStart={() => setFailed(false)}
      onLoadEnd={() => void revealLegacyDrafts()}
      onError={() => setFailed(true)}
      onShouldStartLoadWithRequest={request => {
        if (request.url === 'about:blank' || request.url.startsWith(PRODUCTION_ORIGIN + '/') || request.url === PRODUCTION_ORIGIN) return true;
        return false;
      }}
    />
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#fff' },
  failure: { padding: 12, backgroundColor: '#fff1df' },
  error: { color: '#9c3131' }, failureActions: { flexDirection: 'row', gap: 8 },
  retry: { alignSelf: 'flex-start', padding: 8, marginTop: 6, borderWidth: 1, borderColor: '#dce3eb', borderRadius: 8 },
  actionText: { color: '#172b44', fontSize: 14 },
});
