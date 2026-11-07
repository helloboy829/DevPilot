"use client";

import { useRef, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreateAgent } from "@/core/agents";
import {
  buildManualAssistant,
  EVALUATION_ASSISTANT_PRESETS,
} from "@/core/agents/evaluation-presets";
import { useI18n } from "@/core/i18n/hooks";

export function ManualAssistantDialog({ onClose }: { onClose: () => void }) {
  const { locale } = useI18n();
  const zh = locale === "zh-CN";
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [soul, setSoul] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const create = useCreateAgent();
  const save = async () => {
    if (lock.current) return;
    let request;
    try {
      request = buildManualAssistant({ name, description, soul });
    } catch {
      setError(
        zh
          ? "名称仅支持1–64位英文字母、数字和连字符；描述不超过500字，指令须为1–12000字。"
          : "Use 1–64 letters, digits or hyphens for the name, up to 500 characters for the description and 1–12000 characters for instructions.",
      );
      return;
    }
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await create.mutateAsync(request);
      onClose();
    } catch {
      setError(
        zh
          ? "保存失败：名称可能已存在，或服务不可用。请检查后重试；输入已保留。"
          : "Could not save: the name may already exist or the service is unavailable. Check and retry; your input is retained.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !lock.current) onClose();
      }}
    >
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
        aria-busy={busy}
      >
        <DialogHeader>
          <DialogTitle>
            {zh ? "手动配置助手" : "Configure assistant manually"}
          </DialogTitle>
          <DialogDescription>
            {zh
              ? "无需模型即可保存配置；对话需要可用模型。预设仅辅助人工评测，不产生正式结论。"
              : "Save configuration without a model; conversations require an available model. Presets assist human evaluation, not official decisions."}
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={busy} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="assistant-preset">
                {zh ? "角色预设" : "Role preset"}
              </label>
              <select
                id="assistant-preset"
                defaultValue=""
                className="border-input bg-background w-full rounded-md border px-3 py-2 text-sm"
                onChange={(event) => {
                  const preset = EVALUATION_ASSISTANT_PRESETS.find(
                    (item) => item.id === event.target.value,
                  );
                  if (preset) {
                    setDescription(preset.title[locale]);
                    setSoul(preset.soul[locale]);
                    setError("");
                  }
                }}
              >
                <option value="">
                  {zh
                    ? "选择预设以填入指令（覆盖当前描述与指令）"
                    : "Choose a preset to replace description and instructions"}
                </option>
                {EVALUATION_ASSISTANT_PRESETS.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.title[locale]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="assistant-manual-name"
              >
                {zh ? "助手名称" : "Assistant name"}
              </label>
              <Input
                id="assistant-manual-name"
                autoComplete="off"
                maxLength={64}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="evaluation-advisor"
                required
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="assistant-manual-description"
              >
                {zh ? "描述" : "Description"}
              </label>
              <Input
                id="assistant-manual-description"
                maxLength={500}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="assistant-manual-instructions"
              >
                {zh ? "行为指令" : "Instructions"}
              </label>
              <Textarea
                id="assistant-manual-instructions"
                className="min-h-40"
                maxLength={12000}
                value={soul}
                onChange={(event) => setSoul(event.target.value)}
                required
              />
            </div>
            <p className="text-muted-foreground text-xs">
              {zh
                ? "不预选配置工具组或技能；这不是无工具沙箱，框架内置工具、MCP、记忆和模型调用仍受平台权限与配置控制。不要在指令中粘贴密钥、未授权材料或隐藏金标。"
                : "No configured tool groups or skills are selected. This is not a tool-free sandbox: built-in tools, MCP, memory and model calls remain governed by platform permissions and configuration. Do not paste secrets, unauthorized materials or hidden reference answers."}
            </p>
            {error && (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={onClose}>
                {zh ? "取消" : "Cancel"}
              </Button>
              <Button type="submit">
                {busy
                  ? zh
                    ? "保存中…"
                    : "Saving…"
                  : zh
                    ? "保存助手"
                    : "Save assistant"}
              </Button>
            </div>
          </fieldset>
        </form>
      </DialogContent>
    </Dialog>
  );
}
