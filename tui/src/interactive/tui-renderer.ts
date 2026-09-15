import {
  ProcessTerminal,
  type Terminal,
  TuiAltScreen,
  TuiMainScreen,
} from "@earendil-works/pi-tui";

export interface InteractiveTuiOptions {
  readonly tuiMode?: "regular" | "fullscreen";
  readonly showHardwareCursor?: boolean;
  readonly logDirectory?: string;
  readonly terminal?: Terminal;
}

export function createInteractiveTui(
  options: InteractiveTuiOptions = {},
): TuiMainScreen | TuiAltScreen {
  const terminal = options.terminal ?? new ProcessTerminal();
  const showCursor = options.showHardwareCursor ?? false;
  const logDir = options.logDirectory ?? "";
  if (options.tuiMode === "fullscreen") {
    return new TuiAltScreen(terminal, showCursor, logDir);
  }
  return new TuiMainScreen(terminal, showCursor, logDir);
}
