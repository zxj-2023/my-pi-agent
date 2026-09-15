import { Container, Spacer, Text } from "@earendil-works/pi-tui";
import { theme } from "../theme/theme.js";

export class HeaderComponent extends Container {
  constructor(version = "0.1.0") {
    super();

    this.addChild(new Spacer(1));

    const logo =
      theme.bold(theme.fg("accent", "my-pi-agent")) +
      theme.fg("dim", ` v${version}`);

    const hints = [
      theme.fg("dim", "Esc") + theme.fg("muted", " interrupt"),
      theme.fg("dim", "Ctrl+C") + theme.fg("muted", " clear/exit"),
      theme.fg("dim", "/") + theme.fg("muted", " commands"),
      theme.fg("dim", "!") + theme.fg("muted", " bash"),
      theme.fg("dim", "Ctrl+O") + theme.fg("muted", " expand"),
    ].join(theme.fg("muted", " · "));

    const onboarding = theme.fg(
      "dim",
      "欢迎使用 my-pi-agent！输入需求或按 / 开启命令菜单。",
    );

    const content = `${logo}\n${hints}\n\n${onboarding}`;
    this.addChild(new Text(content, 1, 0));
    this.addChild(new Spacer(1));
  }
}
