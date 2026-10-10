import { Editor, visibleWidth } from "@earendil-works/pi-tui";
import { spawn } from "node:child_process";
import { platform } from "node:process";
import type { MessageContent, MessageContentBlock } from "../protocol.js";
import { type StatusIndicator } from "./status-indicator.js";

export interface CustomEditorOptions {
  embedWorkingStatus?: boolean;
  paddingX?: number;
  autocompleteMaxVisible?: number;
}

export interface ImageAttachment {
  marker: string;
  data: string;
  mime_type: "image/png" | "image/jpeg" | "image/webp" | "image/gif";
  position: number;
}

function runClipboardCommand(command: string, args: string[], timeoutMs = 1500): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    let timer: NodeJS.Timeout | undefined;
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "ignore"] });
    const chunks: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => chunks.push(chunk));

    const cleanup = () => {
      if (timer) clearTimeout(timer);
    };

    timer = setTimeout(() => {
      cleanup();
      try {
        child.kill("SIGKILL");
      } catch {
        // ignore
      }
      reject(new Error(`${command} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.once("error", (err) => {
      cleanup();
      reject(err);
    });
    child.once("close", (code) => {
      cleanup();
      if (code === 0) resolve(Buffer.concat(chunks));
      else reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

async function readClipboardImage(): Promise<Omit<ImageAttachment, "marker" | "position"> | undefined> {
  if (platform === "linux") {
    for (const command of ["wl-paste", "xclip"]) {
      let commandAvailable = true;
      for (const mime_type of ["image/png", "image/jpeg", "image/webp", "image/gif"] as const) {
        if (!commandAvailable) break;
        try {
          const args = command === "wl-paste"
            ? ["--no-newline", "--type", mime_type]
            : ["-selection", "clipboard", "-t", mime_type, "-o"];
          const data = await runClipboardCommand(command, args);
          if (data.length > 0) return { data: data.toString("base64"), mime_type };
        } catch (err: any) {
          if (err && (err.code === "ENOENT" || err.message?.includes("ENOENT"))) {
            commandAvailable = false;
            break;
          }
          // Try the next clipboard backend or image type.
        }
      }
    }
  } else if (platform === "darwin") {
    try {
      const output = await runClipboardCommand("osascript", [
        "-e",
        "the clipboard as «class PNGf»",
      ]);
      const hex = output.toString().match(/«data PNGf([0-9a-f]+)»/i)?.[1];
      if (hex) return { data: Buffer.from(hex, "hex").toString("base64"), mime_type: "image/png" };
    } catch {
      return undefined;
    }
  } else if (platform === "win32") {
    try {
      const output = await runClipboardCommand("powershell", [
        "-NoProfile",
        "-STA",
        "-Command",
        "Add-Type -AssemblyName System.Windows.Forms; $image = [Windows.Forms.Clipboard]::GetImage(); if ($image) { $stream = New-Object IO.MemoryStream; $image.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png); [Convert]::ToBase64String($stream.ToArray()) }",
      ]);
      const data = output.toString().trim();
      if (data) return { data, mime_type: "image/png" };
    } catch {
      return undefined;
    }
  }
  return undefined;
}

/**
 * 扩展版 Editor（100% 对标 Pi 原厂 CustomEditor）：
 * 支持在输入框顶部边框实时嵌入转圈动效：── ⠸ Working ─────────────────────────
 */
export class CustomEditor extends Editor {
  public embedWorkingStatus: boolean;
  private workingStatusIndicator?: StatusIndicator;
  private imageAttachments = new Map<string, Omit<ImageAttachment, "marker" | "position">>();
  private imageCounter = 0;
  private pendingImagePastes = 0;
  private submitDisabledBeforePaste = false;

  constructor(tui: any, theme: any, options?: CustomEditorOptions) {
    super(tui, theme, options);
    this.embedWorkingStatus = options?.embedWorkingStatus ?? true;
  }

  public setWorkingStatusIndicator(indicator?: StatusIndicator): void {
    this.workingStatusIndicator = indicator;
    this.tui.requestRender();
  }

  public async pasteImageFromClipboard(): Promise<boolean> {
    if (this.pendingImagePastes++ === 0) {
      this.submitDisabledBeforePaste = this.disableSubmit;
      this.disableSubmit = true;
    }
    const marker = this.insertImageMarker();
    try {
      const image = await readClipboardImage();
      if (!image) {
        this.setText(this.getExpandedText().replace(marker, ""));
        return false;
      }
      this.imageAttachments.set(marker, image);
      return true;
    } finally {
      if (--this.pendingImagePastes === 0) this.disableSubmit = this.submitDisabledBeforePaste;
    }
  }

  public insertImageAttachment(image: Omit<ImageAttachment, "marker" | "position">): void {
    const marker = this.insertImageMarker();
    this.imageAttachments.set(marker, image);
  }

  private insertImageMarker(): string {
    const marker = `[image ${++this.imageCounter}]`;
    this.insertTextAtCursor(marker);
    this.tui.requestRender();
    return marker;
  }

  public getImageAttachments(text = this.getExpandedText()): ImageAttachment[] {
    const attachments: ImageAttachment[] = [];
    for (const match of text.matchAll(/\[image \d+\]/g)) {
      const image = this.imageAttachments.get(match[0]);
      if (image) attachments.push({ marker: match[0], ...image, position: match.index });
    }
    return attachments;
  }

  public getMessageContent(text = this.getExpandedText()): MessageContent {
    const attachments = this.getImageAttachments(text);
    if (attachments.length === 0) return text;

    const blocks: MessageContentBlock[] = [];
    let cursor = 0;
    for (const attachment of attachments) {
      const position = attachment.position;
      if (position > cursor) blocks.push({ type: "text", text: text.slice(cursor, position) });
      blocks.push({ type: "image", data: attachment.data, mime_type: attachment.mime_type });
      cursor = position + attachment.marker.length;
    }
    if (cursor < text.length) blocks.push({ type: "text", text: text.slice(cursor) });
    return blocks;
  }

  public setMessageContent(content: MessageContent): void {
    this.setText("");
    if (typeof content === "string") {
      this.setText(content);
    } else {
      for (const block of content) {
        if (block.type === "text") this.insertTextAtCursor(block.text);
        else this.insertImageAttachment(block);
      }
    }
  }

  public override renderTopBorder(
    width: number,
    hiddenLineCount: number,
  ): string {
    if (
      !this.embedWorkingStatus ||
      !this.workingStatusIndicator ||
      width <= 0
    ) {
      return super.renderTopBorder(width, hiddenLineCount);
    }

    let status = this.workingStatusIndicator.renderInBorder(
      Math.max(1, width - 5),
    );
    let statusWidth = visibleWidth(status);
    if (statusWidth === 0) {
      return super.renderTopBorder(width, hiddenLineCount);
    }

    const overflowLabel =
      hiddenLineCount > 0 ? ` ↑ ${hiddenLineCount} more ` : undefined;
    const overflowLabelWidth = overflowLabel ? visibleWidth(overflowLabel) : 0;
    const overflowStart = Math.floor((width - overflowLabelWidth) / 2);
    const canFitOverflow = () =>
      overflowLabel !== undefined &&
      overflowLabelWidth + 2 <= width &&
      overflowStart - (3 + statusWidth + 1) >= 1;

    if (overflowLabel && !canFitOverflow()) {
      status = this.workingStatusIndicator.renderSpinnerInBorder(width);
      statusWidth = visibleWidth(status);
    }

    if (canFitOverflow()) {
      const leftBlockWidth = 3 + statusWidth + 1;
      return (
        this.borderColor("── ") +
        status +
        this.borderColor(
          ` ${"─".repeat(overflowStart - leftBlockWidth)}${overflowLabel}${"─".repeat(
            Math.max(0, width - overflowStart - overflowLabelWidth),
          )}`,
        )
      );
    }

    if (width >= statusWidth + 5) {
      return (
        this.borderColor("── ") +
        status +
        this.borderColor(` ${"─".repeat(Math.max(0, width - statusWidth - 4))}`)
      );
    }

    status = this.workingStatusIndicator.renderSpinnerInBorder(width);
    statusWidth = visibleWidth(status);
    const prefixWidth = Math.min(3, Math.max(0, width - statusWidth));
    return (
      this.borderColor("─".repeat(prefixWidth)) +
      status +
      this.borderColor(
        "─".repeat(Math.max(0, width - prefixWidth - statusWidth)),
      )
    );
  }
}
