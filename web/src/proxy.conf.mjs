/**
 * Where the dev server sends API calls, so the browser sees one address and needs no CORS.
 *
 * Keys starting with "^" are patterns. A plain key such as "/chat" matches every path that
 * starts with it, which includes the app's own /chat-page-*.js.
 */
const api = {
  target: 'http://127.0.0.1:8000',
  secure: false,
  configure: (proxy) => {
    // When the API stops in the middle of a response, the proxy leaves the browser waiting
    // for the rest. Closing the connection lets the page see that it was lost.
    proxy.on('proxyRes', (fromApi, _request, toBrowser) => {
      fromApi.on('close', () => {
        if (!fromApi.complete) {
          toBrowser.destroy();
        }
      });
    });
  },
};

export default {
  '^/(chat|health)$': api,
  '^/threads/': api,
};
