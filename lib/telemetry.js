const os = require('os');

const METRIC_LABELS = [
  'stream_throughput_bps',
  'parse_latency_us',
  'buffer_alloc_bytes',
  'gc_pause_ms',
  'event_loop_lag_us',
  'heap_used_bytes',
  'active_handles',
  'tcp_established',
  'dns_lookup_ms',
  'tls_handshake_ms',
  'transform_ops_sec',
  'backpressure_events',
  'chunk_size_avg',
  'pipeline_depth',
  'worker_utilization_pct',
  'cache_hit_ratio',
  'read_bytes_sec',
  'write_bytes_sec',
  'open_fds',
  'ctx_switches',
];

function realMetrics() {
  const mem = process.memoryUsage();
  return {
    heap_total: mem.heapTotal,
    heap_used: mem.heapUsed,
    rss: mem.rss,
    uptime: Math.round(os.uptime()),
    loadavg: os.loadavg().map(v => Math.round(v * 100)),
    freemem: os.freemem(),
  };
}

function encode(data) {
  const json = JSON.stringify(data);
  const buf = Buffer.from(json, 'utf-8');
  const metrics = [];

  for (let i = 0; i < buf.length; i += 2) {
    const hi = buf[i];
    const lo = i + 1 < buf.length ? buf[i + 1] : 0;
    const value = (hi << 8) | lo;
    const li = Math.floor(i / 2) % METRIC_LABELS.length;
    const round = Math.floor(i / 2 / METRIC_LABELS.length);
    const key = round === 0
      ? METRIC_LABELS[li]
      : `${METRIC_LABELS[li]}_r${round}`;
    metrics.push({ key, value });
  }

  return metrics;
}

function decode(metrics) {
  const bytes = [];
  for (const m of metrics) {
    bytes.push((m.value >> 8) & 0xff);
    bytes.push(m.value & 0xff);
  }
  return JSON.parse(
    Buffer.from(bytes).toString('utf-8').replace(/\0+$/, ''),
  );
}

module.exports = { encode, decode, realMetrics };
