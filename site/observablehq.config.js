export default {
  title: "music-story",
  root: "src",
  output: "dist",
  head: `<script>
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
