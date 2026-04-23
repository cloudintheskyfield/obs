const http = require("http");

const listenHost = process.env.OBS_PROXY_HOST || "0.0.0.0";
const listenPort = Number(process.env.OBS_PROXY_PORT || 8000);
const targetHost = process.env.OBS_TARGET_HOST || "127.0.0.1";
const targetPort = Number(process.env.OBS_TARGET_PORT || 8001);

const server = http.createServer((req, res) => {
  const options = {
    hostname: targetHost,
    port: targetPort,
    path: req.url,
    method: req.method,
    headers: {
      ...req.headers,
      host: `${targetHost}:${targetPort}`,
    },
  };

  const proxyReq = http.request(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on("error", (error) => {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`proxy error: ${error.message}`);
  });

  req.pipe(proxyReq);
});

server.on("clientError", (_error, socket) => {
  socket.end("HTTP/1.1 400 Bad Request\r\n\r\n");
});

server.listen(listenPort, listenHost, () => {
  console.log(
    `HTTP proxy listening on http://${listenHost}:${listenPort} -> http://${targetHost}:${targetPort}`
  );
});
