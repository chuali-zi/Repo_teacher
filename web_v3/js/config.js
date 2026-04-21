window.RTV3 = window.RTV3 || {};

window.RTV3.TWEAK_DEFAULTS = {
  theme: "teal",
  showLeftPanel: true,
  showRightPanel: true,
  scanlines: false,
  glowIntensity: "medium",
};

window.RTV3.API_BASE = (function () {
  const meta = document.querySelector('meta[name="rt-api-base"]');
  if (meta && meta.content) return meta.content.replace(/\/+$/, "");
  const host = location.hostname || "127.0.0.1";
  return "http://" + host + ":8000";
})();

window.RTV3.STEP_LABELS = {
  repo_access: "REPO ACCESS",
  file_tree_scan: "FILE TREE SCAN",
  research_planning: "RESEARCH PLANNING",
  source_sweep: "SOURCE SWEEP",
  chapter_synthesis: "CHAPTER SYNTHESIS",
  final_report_write: "FINAL REPORT WRITE",
  entry_and_module_analysis: "ENTRY DETECTION",
  dependency_analysis: "DEP ANALYSIS",
  skeleton_assembly: "SKELETON BUILD",
  initial_report_generation: "REPORT GEN",
};

window.RTV3.QUICK_GUIDE_STEPS = [
  "repo_access",
  "file_tree_scan",
  "entry_and_module_analysis",
  "dependency_analysis",
  "skeleton_assembly",
  "initial_report_generation",
];

window.RTV3.DEEP_RESEARCH_STEPS = [
  "repo_access",
  "file_tree_scan",
  "research_planning",
  "source_sweep",
  "chapter_synthesis",
  "final_report_write",
];

window.RTV3.VIEW_MAP = { input: "input", analysis: "analyzing", chat: "chatting" };
