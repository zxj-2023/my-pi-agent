import { matchesKey } from "@earendil-works/pi-tui";

/**
 * 统一回车判断函数，兼容跨平台回车按键：
 * 包括 VT100/ANSI 单字符 \r, \n，以及 Windows ConPTY / SSH 的 \r\n，和 pi-tui 的 return/enter
 */
export function isEnterKey(data: string): boolean {
   return (
      matchesKey(data, "return") ||
      matchesKey(data, "enter") ||
      data === "\r" ||
      data === "\n" ||
      data === "\r\n"
   );
}
