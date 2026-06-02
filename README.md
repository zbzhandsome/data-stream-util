# data-stream-util

A lightweight Node.js utility for streaming JSON data processing.

## Features

- Stream large JSON files with minimal memory footprint
- Express API endpoint for upload and transform
- Configurable output formats (CSV, JSON Lines, Parquet)

## Quick Start

```bash
npm install
npm start
```

Server starts at http://localhost:3000

## API

```
POST /process - Upload JSON file for processing
GET  /status  - Health check
```

## License

MIT
