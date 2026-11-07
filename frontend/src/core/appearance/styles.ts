export const WORKSPACE_STYLE_STORAGE_KEY = "devpilot-workspace-style";

export const WORKSPACE_STYLES = [
  {
    id: "console",
    name: { "en-US": "Precision console", "zh-CN": "精密控制台" },
    description: {
      "en-US": "Cobalt accents, crisp borders, compact instruments.",
      "zh-CN": "钴蓝强调色、清晰边界，适合高密度评测。",
    },
    swatches: ["#eff4fb", "#ffffff", "#2358c9", "#17243b"],
  },
  {
    id: "graphite",
    name: { "en-US": "Graphite minimal", "zh-CN": "石墨极简" },
    description: {
      "en-US": "Quiet monochrome with reduced visual noise.",
      "zh-CN": "低干扰黑白灰，聚焦数据和证据。",
    },
    swatches: ["#f4f4f5", "#ffffff", "#303036", "#18181b"],
  },
  {
    id: "forest",
    name: { "en-US": "Forest lab", "zh-CN": "森林实验室" },
    description: {
      "en-US": "Cool green surfaces for extended review sessions.",
      "zh-CN": "冷绿层次，适合长时间样本复核。",
    },
    swatches: ["#edf5f1", "#ffffff", "#17634c", "#16372c"],
  },
  {
    id: "paper",
    name: { "en-US": "Paper studio", "zh-CN": "暖纸工作室" },
    description: {
      "en-US": "Warm paper, editorial spacing, understated depth.",
      "zh-CN": "暖纸底色、舒展间距，适合阅读与报告。",
    },
    swatches: ["#f8f3e9", "#fffcf6", "#8b4f23", "#3e3025"],
  },
  {
    id: "violet",
    name: { "en-US": "Violet atelier", "zh-CN": "紫罗兰工坊" },
    description: {
      "en-US": "Violet highlights, soft surfaces, rounded panels.",
      "zh-CN": "紫色重点、柔和层次与圆润面板。",
    },
    swatches: ["#f4f0fc", "#ffffff", "#7040bf", "#302143"],
  },
] as const;
export type WorkspaceStyle = (typeof WORKSPACE_STYLES)[number]["id"];
export function normalizeWorkspaceStyle(value: unknown): WorkspaceStyle {
  return WORKSPACE_STYLES.find((style) => style.id === value)?.id ?? "console";
}
