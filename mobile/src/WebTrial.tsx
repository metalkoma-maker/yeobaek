import React, { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { PRODUCTION_ORIGIN } from './api';

export function WebTrial({ onBack }: { onBack: () => void }) {
  const [failed, setFailed] = useState(false);
  const confirmBack = () => Alert.alert('기존 앱으로 돌아가기', '웹 화면의 저장 상태를 먼저 확인해 주세요. 저장되지 않은 입력은 웹 화면의 기기 보관본에서 확인해야 할 수 있습니다.', [
    { text: '계속 쓰기', style: 'cancel' },
    { text: '돌아가기', onPress: onBack },
  ]);
  return <SafeAreaView style={styles.root}>
    <View style={styles.bar}>
      <Pressable accessibilityRole="button" onPress={confirmBack} style={styles.back}><Text style={styles.backText}>← 기존 앱</Text></Pressable>
      <Text style={styles.title}>웹 화면 시험</Text>
    </View>
    {failed && <Text accessibilityRole="alert" style={styles.error}>웹 화면을 열지 못했습니다. 인터넷 연결을 확인해 주세요. 기존 앱으로 돌아갈 수 있습니다.</Text>}
    <WebView
      source={{ uri: PRODUCTION_ORIGIN }}
      originWhitelist={[PRODUCTION_ORIGIN]}
      javaScriptEnabled
      domStorageEnabled
      incognito={false}
      sharedCookiesEnabled={false}
      onLoadStart={() => setFailed(false)}
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
  bar: { height: 48, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, borderBottomWidth: 1, borderColor: '#e1e7ee', gap: 12 },
  back: { padding: 8 }, backText: { color: '#172b44', fontSize: 14 }, title: { color: '#64758b', fontSize: 13 },
  error: { padding: 12, color: '#9c3131', backgroundColor: '#fff1df' },
});
