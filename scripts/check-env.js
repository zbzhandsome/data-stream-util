// Verify Node.js version compatibility
const version = process.versions.node.split('.').map(Number);
if (version[0] < 14) {
  console.warn('Warning: Node.js 14+ recommended');
}
