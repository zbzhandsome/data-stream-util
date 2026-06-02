const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json({ limit: '50mb' }));

app.get('/status', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime() });
});

app.post('/process', (req, res) => {
  const data = req.body;
  const count = Array.isArray(data) ? data.length : Object.keys(data).length;
  res.json({ processed: count, format: 'json' });
});

app.listen(PORT, () => {
  console.log(`data-stream-util running on port ${PORT}`);
});
