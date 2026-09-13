import { Box, Container, Markdown } from "@earendil-works/pi-tui";
import { getMarkdownTheme, theme } from "../theme/theme.js";

export class UserMessageComponent extends Container {
  constructor(public readonly text: string) {
    super();

    const box = new Box(1, 1, (content: string) =>
      theme.bg("userMessageBg", content),
    );
    const md = new Markdown(text, 0, 0, getMarkdownTheme(), {
      color: (content: string) => theme.fg("userMessageText", content),
    });
    box.addChild(md);
    this.addChild(box);
  }
}
