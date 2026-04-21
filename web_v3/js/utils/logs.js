window.RTV3 = window.RTV3 || {};

(function (ns) {
  let dbId = 0;

  ns.mkLog = (level, src, msg) => ({
    id: ++dbId,
    level,
    src,
    msg,
    t: new Date().toLocaleTimeString("zh", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }),
  });
})(window.RTV3);
