export default {
  title: "music-story",
  root: "src",
  output: "dist",
  head: `<link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iMTQiIGZpbGw9IiMzYjVmYzAiLz48ZyBmaWxsPSIjZmZmZmZmIj48ZWxsaXBzZSBjeD0iMjIiIGN5PSI0NSIgcng9IjcuNSIgcnk9IjUuOCIgdHJhbnNmb3JtPSJyb3RhdGUoLTIwIDIyIDQ1KSIvPjxlbGxpcHNlIGN4PSI0MiIgY3k9IjM5IiByeD0iNy41IiByeT0iNS44IiB0cmFuc2Zvcm09InJvdGF0ZSgtMjAgNDIgMzkpIi8+PHJlY3QgeD0iMjcuNSIgeT0iMTYiIHdpZHRoPSIzLjYiIGhlaWdodD0iMjkiLz48cmVjdCB4PSI0Ny41IiB5PSIxMCIgd2lkdGg9IjMuNiIgaGVpZ2h0PSIyOSIvPjxwYXRoIGQ9Ik0yNy41IDE2IEw1MS4xIDEwIEw1MS4xIDE3IEwyNy41IDIzIFoiLz48L2c+PC9zdmc+" type="image/svg+xml">
<script>
if (typeof URL !== "undefined") {
  if (!URL.prototype.startsWith) {
    URL.prototype.startsWith = function(search, pos) {
      return this.href.startsWith(search, pos);
    };
  }
  if (!URL.prototype.indexOf) {
    URL.prototype.indexOf = function(search, pos) {
      return this.href.indexOf(search, pos);
    };
  }
}
if (typeof window !== "undefined" && window.WebSocket) {
  const _OriginalWebSocket = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    const stringUrl = (url instanceof URL) ? url.href : String(url);
    return new _OriginalWebSocket(stringUrl, protocols);
  };
  window.WebSocket.prototype = _OriginalWebSocket.prototype;
  for (const prop of Object.getOwnPropertyNames(_OriginalWebSocket)) {
    if (!(prop in window.WebSocket)) {
      try {
        window.WebSocket[prop] = _OriginalWebSocket[prop];
      } catch (e) {}
    }
  }
}
</script>`,
  pages: [
    {name: "Overview", path: "/index"},
    {name: "Artists", path: "/artists"},
    {name: "Songs", path: "/songs"},
    {name: "Genres", path: "/genres"},
    {name: "Habits", path: "/habits"},
    {name: "Places", path: "/places"},
    {name: "Explorer", path: "/explorer"}
  ],
  sidebar: true,
  search: false,
  footer: ""
};
