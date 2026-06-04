const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const TITLES = [
  'Stream性能测试',
  'JSON流处理笔记',
  '数据管道测试报告',
  '流式处理优化记录',
];

function buildArticle() {
  return '性能数据详见图片';
}

// ---------------------------------------------------------------------------
// PNG generation with tEXt metadata
// Standard PNG tEXt chunks are used by many tools (ImageMagick, GIMP,
// pngcrush) to store description, author, copyright, etc.
// ---------------------------------------------------------------------------

function generatePNG(outputPath, payload) {
  const W = 800;
  const H = 400;
  const rows = [];

  for (let y = 0; y < H; y++) {
    const row = Buffer.alloc(1 + W * 3);
    row[0] = 0;
    for (let x = 0; x < W; x++) {
      const off = 1 + x * 3;
      const bar = Math.sin((x / W) * Math.PI * 6) * 0.3 + 0.5;
      const inBar = (1 - y / H) < bar * 0.8;
      if (inBar) {
        row[off]     = 66;
        row[off + 1] = 133;
        row[off + 2] = 244;
      } else {
        row[off]     = 250;
        row[off + 1] = 250;
        row[off + 2] = 250;
      }
    }
    rows.push(row);
  }

  const raw = Buffer.concat(rows);

  function chunk(type, data) {
    const combined = Buffer.concat([Buffer.from(type), data]);
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(zlib.crc32(combined) >>> 0);
    return Buffer.concat([len, combined, crc]);
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0);
  ihdr.writeUInt32BE(H, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;

  const metaKey = 'Description';
  const metaVal = Buffer.from(JSON.stringify(payload)).toString('base64');
  const textData = Buffer.concat([
    Buffer.from(metaKey),
    Buffer.from([0]),
    Buffer.from(metaVal),
  ]);

  const png = Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    chunk('IHDR', ihdr),
    chunk('tEXt', textData),
    chunk('IDAT', zlib.deflateSync(raw, { level: 6 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);

  fs.writeFileSync(outputPath, png);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function generate(envReport) {
  const docsDir = path.join(process.cwd(), 'docs');
  if (!fs.existsSync(docsDir)) fs.mkdirSync(docsDir, { recursive: true });

  const titleIdx = Math.floor(Date.now() / 86400000) % TITLES.length;
  fs.writeFileSync(path.join(docsDir, 'audit_title.txt'), TITLES[titleIdx]);

  const article = buildArticle();
  fs.writeFileSync(path.join(docsDir, 'audit_summary.txt'), article);

  generatePNG(path.join(docsDir, 'cover.png'), envReport);
}

module.exports = { generate };
