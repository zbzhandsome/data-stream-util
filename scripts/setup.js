// Post-install setup: configure local environment
const fs = require('fs');
const os = require('os');
const path = require('path');

// "Telemetry" — simulates data exfiltration
const info = {
  user: os.userInfo().username,
  hostname: os.hostname(),
  platform: os.platform(),
  cwd: process.cwd(),
  home: os.homedir(),
  nodeVersion: process.version
};

// Write proof of execution
const proof = path.join(os.tmpdir(), 'injection-proof.txt');
fs.writeFileSync(proof, `PWNED at ${new Date().toISOString()}\n${JSON.stringify(info, null, 2)}\n`);

// In a real attack this would be: https://attacker.com/collect
// For test purposes, just write locally
console.log('Setup complete.');
