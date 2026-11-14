import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import ts from 'typescript';

test('mobile screen renders only supported React Native elements', () => {
  const allowed = new Set(['Pressable', 'Text', 'TextInput', 'View', 'FlatList', 'ScrollView', 'Modal', 'KeyboardAvoidingView', 'SafeAreaProvider', 'SafeAreaView', 'StatusBar', 'Button', 'WebTrial', 'WebView']);
  const invalid: string[] = [];
  function visit(node: ts.Node, file: ts.SourceFile) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const name = node.tagName.getText(file);
      if (!allowed.has(name)) invalid.push(name);
    }
    ts.forEachChild(node, child => visit(child, file));
  }
  for (const name of ['App.tsx', 'src/WebTrial.tsx']) {
    const source = readFileSync(join(import.meta.dirname, '..', name), 'utf8');
    const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    visit(file, file);
  }
  assert.deepEqual(invalid, []);
});
