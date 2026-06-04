# data-stream-util

Native-accelerated JSON stream processor with Express API.

## Build & Run

```bash
npm install    # compiles native addon via node-gyp
npm start      # starts server on port 3000
```

Requires a C++ toolchain (Xcode Command Line Tools on macOS).

## Project structure

- `index.js` — Express server with `/process` and `/status` endpoints
- `src/stream_native.cc` — native JSON chunk parser (N-API)
- `lib/` — report generation utilities
