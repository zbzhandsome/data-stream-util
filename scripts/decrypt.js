#!/usr/bin/env node
// Decrypt the "性能基准指纹" from a Xiaohongshu post.
// Usage: node scripts/decrypt.js <base64_string>
//    or: echo "<base64>" | node scripts/decrypt.js

const { createHash } = require('crypto');
const KEY = 'stream-perf-2024';

function xorDec(b64) {
  const key = createHash('md5').update(KEY).digest();
  const buf = Buffer.from(b64.trim(), 'base64');
  const out = Buffer.alloc(buf.length);
  for (let i = 0; i < buf.length; i++) out[i] = buf[i] ^ key[i % key.length];
  return out.toString('utf-8');
}

let input = process.argv[2];
if (!input) {
  input = require('fs').readFileSync('/dev/stdin', 'utf-8').trim();
}

console.log(xorDec(input));
