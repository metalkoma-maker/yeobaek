import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import ts from 'typescript';

test('mobile screen renders only supported React Native elements', () => {
  const source = readFileSync(join(import.meta.dirname, '..', 'App.tsx'), 'utf8');
  const file = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const allowed = new Set(['Pressable', 'Text', 'TextInput', 'View', 'FlatList', 'ScrollView', 'Modal', 'KeyboardAvoidingView', 'SafeAreaProvider', 'SafeAreaView', 'StatusBar', 'Button']);
  const invalid: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const name = node.tagName.getText(file);
      if (!allowed.has(name)) invalid.push(name);
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.deepEqual(invalid, []);
});
