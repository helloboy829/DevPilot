"""DevPilot「AI 组件测试工具包」核心（纯逻辑 + httpx 出站，零 DeerFlow 依赖）。

对外能力分两层：

- 执行（run）：调接口 → 存 raw（原始返回）
- 评估（eval）：读 raw → 按验证类型/硬阈值判定 → PASS/FAIL

执行与评估严格分离（skill 铁律）：eval 支持显式传 raw 文件路径反复重评。

子模块：
    transports  协议适配（http_post / openai_chat / dify_chat / dify_workflow）
    effect      效果测试（reference_text LLM-judge + manual_review）
    perf        性能测试（延迟/TTFT/QPS/吞吐/成功率）
    report      JSON 报告组装
"""

from devpilot.toolkit import effect, perf, report, transports

__all__ = ["effect", "perf", "report", "transports"]
