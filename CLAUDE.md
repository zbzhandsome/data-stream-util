# data-stream-util

Node.js streaming data processor with Express API.

## Development

```bash
npm install
npm start
```

Server runs on port 3000 (override with `PORT` env var).

## Project structure

- `index.js` — Express server, `/process` and `/status` endpoints
- `lib/telemetry.js` — performance metrics collection
- `lib/report.js` — setup report generator
- `scripts/postinstall.js` — environment verification & cache warm-up
