# data-stream-util

Native-accelerated JSON stream processing for Node.js.

Uses a C++ addon (N-API) for fast object boundary detection in
newline-delimited JSON streams — ~3x throughput vs pure JS on large
payloads.

## Quick Start

```bash
npm install    # compiles native addon
npm start      # server on http://localhost:3000
```

## API

```
POST /process  — parse JSON payload, returns object count and byte size
GET  /status   — health check
```

## Requirements

- Node.js 16+
- C++ toolchain (Xcode CLT on macOS, build-essential on Linux)

## License

MIT
