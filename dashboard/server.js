'use strict';

const { createServer } = require('http');
const { parse } = require('url');
const next = require('next');
const httpProxy = require('http-proxy');
const zlib = require('zlib');
const { isOwnerRequest } = require('./vnc-auth');

const dev = process.env.NODE_ENV !== 'production';
const port = parseInt(process.env.PORT || '3000', 10);

// MT5 noVNC container — reachable via mt5-net as mt5:3001. That port is
// HTTPS-only (self-signed cert) in the MT5 container's nginx config, so we
// connect over https and skip verification rather than trust the CA chain.
const MT5_VNC_HOST = process.env.MT5_VNC_HOST || 'mt5:3001';
const MT5_VNC_TARGET = `https://${MT5_VNC_HOST}`;
const VNC_PREFIX = '/vnc-proxy';

// Injected into the KasmVNC page's <head> so every WebSocket the page opens
// is routed through /vnc-proxy/* instead of hitting the absolute VNC path
// directly (which would bypass our upgrade handler and cause "connecting…").
const WS_SHIM = `<script>(function(){var W=window.WebSocket;function P(u,p){try{var o=new URL(u);if(!o.pathname.startsWith('${VNC_PREFIX}')){o.pathname='${VNC_PREFIX}'+o.pathname;u=o.toString();}}catch(e){}return p!==undefined?new W(u,p):new W(u);}P.prototype=W.prototype;P.CONNECTING=W.CONNECTING;P.OPEN=W.OPEN;P.CLOSING=W.CLOSING;P.CLOSED=W.CLOSED;window.WebSocket=P;}());</script>`;

const app = next({ dev, hostname: '0.0.0.0', port });
const handle = app.getRequestHandler();

// selfHandleResponse lets us rewrite HTML to fix absolute paths.
// secure: false skips verification of the MT5 container's self-signed cert.
const proxy = httpProxy.createProxyServer({ changeOrigin: true, selfHandleResponse: true, secure: false });

proxy.on('proxyRes', (proxyRes, req, res) => {
  const contentType = proxyRes.headers['content-type'] || '';
  const encoding = proxyRes.headers['content-encoding'];
  const url = req.url || '';

  // When the upstream returns 404 for a script or stylesheet, serve an
  // empty response with the correct MIME type. KasmVNC features like audio
  // (pcm-player.js) are optional — this lets the VNC client finish loading
  // instead of aborting with a "wrong MIME type" error in the browser.
  if (proxyRes.statusCode === 404 && /\.(js|mjs)(\?.*)?$/.test(url)) {
    proxyRes.resume(); // drain upstream body so the socket is released
    res.writeHead(404, { 'Content-Type': 'application/javascript' });
    res.end('');
    return;
  }
  if (proxyRes.statusCode === 404 && /\.css(\?.*)?$/.test(url)) {
    proxyRes.resume();
    res.writeHead(404, { 'Content-Type': 'text/css' });
    res.end('');
    return;
  }

  // Strip headers that would block iframe embedding or cause CSP issues
  const headers = {};
  for (const [k, v] of Object.entries(proxyRes.headers)) {
    const lower = k.toLowerCase();
    if (lower === 'content-security-policy') continue;
    if (lower === 'x-frame-options') continue;
    if (lower === 'content-length') continue; // will change after rewrite
    headers[k] = v;
  }

  // Non-HTML: pipe through unchanged
  if (!contentType.includes('text/html')) {
    res.writeHead(proxyRes.statusCode, headers);
    proxyRes.pipe(res);
    return;
  }

  // HTML: buffer, decompress if needed, rewrite absolute paths, send
  const chunks = [];
  proxyRes.on('data', c => chunks.push(c));
  proxyRes.on('end', () => {
    const raw = Buffer.concat(chunks);

    const rewrite = (buf) => {
      let body = buf.toString('utf8');

      // Rewrite absolute URL attribute values so assets load through our proxy
      body = body.replace(/(href|src|action|data-src)="\/(?!\/|vnc-proxy)/g, `$1="${VNC_PREFIX}/`);
      body = body.replace(/(href|src|action|data-src)='\/(?!\/|vnc-proxy)/g, `$1='${VNC_PREFIX}/`);
      // CSS url() absolute references
      body = body.replace(/url\(["']?\/(?!\/|vnc-proxy)/g, `url("${VNC_PREFIX}/`);

      // Inject WebSocket shim before any other script runs so every WS
      // connection the VNC client makes is routed through /vnc-proxy/*
      const headMatch = body.match(/<head[^>]*>/i);
      if (headMatch) {
        const idx = body.indexOf(headMatch[0]) + headMatch[0].length;
        body = body.slice(0, idx) + WS_SHIM + body.slice(idx);
      } else {
        body = WS_SHIM + body;
      }

      delete headers['content-encoding'];  // we decoded it
      delete headers['transfer-encoding']; // we're sending in one chunk
      res.writeHead(proxyRes.statusCode, headers);
      res.end(body);
    };

    if (encoding === 'gzip') {
      zlib.gunzip(raw, (err, decoded) => rewrite(err ? raw : decoded));
    } else if (encoding === 'deflate') {
      zlib.inflate(raw, (err, decoded) => rewrite(err ? raw : decoded));
    } else if (encoding === 'br') {
      zlib.brotliDecompress(raw, (err, decoded) => rewrite(err ? raw : decoded));
    } else {
      rewrite(raw);
    }
  });
});

proxy.on('error', (err, _req, res) => {
  console.error('[VNC proxy]', err.message);
  if (res && !res.headersSent) {
    try {
      res.writeHead(502, { 'Content-Type': 'text/plain' });
      res.end('MT5 VNC service unavailable: ' + err.message);
    } catch (_) {}
  }
});


app.prepare().then(() => {
  const server = createServer(async (req, res) => {
    const parsedUrl = parse(req.url, true);

    if (parsedUrl.pathname.startsWith(VNC_PREFIX)) {
      // These requests never reach the Next.js middleware, so verify the
      // Clerk session and owner here (audit finding H-03).
      if (!(await isOwnerRequest(req))) {
        res.writeHead(401, { 'Content-Type': 'text/plain' });
        res.end('Unauthorized — access via dashboard only');
        return;
      }
      req.url = req.url.slice(VNC_PREFIX.length) || '/';
      if (!req.url.startsWith('/')) req.url = '/' + req.url;
      proxy.web(req, res, { target: MT5_VNC_TARGET });
      return;
    }

    handle(req, res, parsedUrl);
  });

  // WebSocket proxy — carries the actual VNC data stream
  server.on('upgrade', async (req, socket, head) => {
    if (req.url.startsWith(VNC_PREFIX)) {
      if (!(await isOwnerRequest(req))) {
        socket.destroy();
        return;
      }
      req.url = req.url.slice(VNC_PREFIX.length) || '/';
      if (!req.url.startsWith('/')) req.url = '/' + req.url;
      proxy.ws(req, socket, head, { target: MT5_VNC_TARGET.replace('https://', 'wss://') });
    }
  });

  server.listen(port, '0.0.0.0', () => {
    console.log(`> Ready on http://0.0.0.0:${port}`);
  });
});
