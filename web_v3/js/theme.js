window.RTV3 = window.RTV3 || {};

(function (ns) {
  const C = {
    bg: "#020A12",
    bgP: "#030E1A",
    bgE: "#051828",
    bgR: "#071F34",
    bgD: "#010508",
    bdr: "#0A3250",
    bdrS: "#083048",
    bdrX: "#0D5070",
    bdrA: "#00604A",
    ink: "#A0EED8",
    inkS: "#70C8B0",
    inkM: "#408A72",
    inkD: "#1E4838",
    inkF: "#0E2820",
    teal: "#00E5B0",
    tealB: "#00FFD0",
    tealD: "#009870",
    tealG: "rgba(0,229,176,0.12)",
    tealV: "rgba(0,229,176,0.06)",
    blue: "#0099EE",
    blueB: "#22CCFF",
    blueD: "#006699",
    blueG: "rgba(0,153,238,0.12)",
    rust: "#FF4466",
    ivy: "#00CC88",
    plum: "#9966FF",
    amber: "#FFAA00",
  };

  const FF = {
    px: '"Press Start 2P",monospace',
    dot: '"DotGothic16","Share Tech Mono",monospace',
    mono: '"Share Tech Mono","JetBrains Mono",monospace',
  };

  const glow = (col = C.teal, r = 8) => `0 0 ${r}px ${col},0 0 ${Math.round(r / 3)}px ${col}`;
  const textGlow = (col = C.teal) => `0 0 8px ${col},0 0 2px ${col}`;

  ns.C = C;
  ns.FF = FF;
  ns.glow = glow;
  ns.textGlow = textGlow;
})(window.RTV3);
